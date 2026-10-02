import os, time, psycopg
from flask import Flask, render_template_string
from kubernetes import client, config

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "keepalivedb")

def get_db_connection():
    return psycopg.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME,
        connect_timeout=3
    )

def get_namespace():
    ns_file = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_file):
        with open(ns_file, "r") as f:
            return f.read().strip()
    return "keepalive"

def get_pod_statuses():
    pods_info = []
    try:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        
        v1 = client.CoreV1Api()
        namespace = get_namespace()
        pod_list = v1.list_namespaced_pod(namespace)
        
        for pod in pod_list.items:
            labels = pod.metadata.labels or {}
            app_label = labels.get("app", "")
            k8s_app_label = labels.get("app.kubernetes.io/name", "")
            
            if "web" in app_label:
                pod_type = "Web Frontend"
            elif "worker" in app_label:
                pod_type = "Worker"
            elif "postgresql" in k8s_app_label or "postgres" in app_label:
                pod_type = "Database (Charmed PostgreSQL)"
            else:
                pod_type = "Other"
            
            ready = False
            if pod.status.container_statuses:
                ready = all(cs.ready for cs in pod.status.container_statuses)
            
            pods_info.append({
                "name": pod.metadata.name,
                "type": pod_type,
                "phase": pod.status.phase,
                "ready": "Ready" if ready else "Not Ready",
                "ip": pod.status.pod_ip or "N/A"
            })
    except Exception as e:
        pods_info.append({
            "name": "Error querying K8s API",
            "type": "N/A",
            "phase": str(e),
            "ready": "N/A",
            "ip": "N/A"
        })
    return pods_info

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Keepalive Dashboard</title>
    <meta http-equiv="refresh" content="60">
    <style>
        body { font-family: Arial, sans-serif; margin: 30px; background-color: #f8f9fa; }
        h2, h3 { color: #212529; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #dee2e6; padding: 10px; text-align: left; }
        th { background-color: #0066cc; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .status-ready { color: green; font-weight: bold; }
        .status-notready { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <h2>Keepalive Status Dashboard</h2>
    <p><i>Auto-refreshing every 60 seconds...</i></p>

    <div class="card">
        <strong>Last Registered Timestamp in DB:</strong> 
        <span style="color: #0066cc; font-size: 1.2em; font-weight: bold;">{{ last_ts }}</span>
    </div>

    <div class="card">
        <h3>Pods Status</h3>
        <table>
            <tr>
                <th>Pod Name</th>
                <th>Component</th>
                <th>Phase</th>
                <th>Health Status</th>
                <th>Pod IP</th>
            </tr>
            {% for pod in pods %}
            <tr>
                <td>{{ pod.name }}</td>
                <td>{{ pod.type }}</td>
                <td>{{ pod.phase }}</td>
                <td class="{{ 'status-ready' if pod.ready == 'Ready' else 'status-notready' }}">{{ pod.ready }}</td>
                <td>{{ pod.ip }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <div class="card">
        <h3>Keepalive Registered Messages Per Minute</h3>
        <table>
            <tr>
                <th>Minute</th>
                <th>Keepalive Count</th>
            </tr>
            {% for row in stats %}
            <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[1] }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT MAX(ts) FROM keepalives;")
        last_ts_row = cur.fetchone()
        last_ts = last_ts_row[0] if last_ts_row and last_ts_row[0] else "No records found"
        
        cur.execute("""
            SELECT date_trunc('minute', ts) as minute, count(*) 
            FROM keepalives 
            GROUP BY minute 
            ORDER BY minute DESC LIMIT 20;
        """)
        stats = cur.fetchall()
        conn.close()
    except Exception as e:
        last_ts = f"DB Error: {e}"
        stats = []

    pods = get_pod_statuses()
    return render_template_string(HTML_TEMPLATE, last_ts=last_ts, stats=stats, pods=pods)

def run_worker():
    print("Starting worker process...")
    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS keepalives (
                    id SERIAL PRIMARY KEY,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("INSERT INTO keepalives (ts) VALUES (NOW());")
            conn.commit()
            cur.close()
            conn.close()
            print("Keepalive written successfully.")
        except Exception as e:
            print(f"Error writing to DB: {e}")
        time.sleep(60)

if __name__ == "__main__":
    mode = os.getenv("APP_MODE", "web")
    if mode == "worker":
        run_worker()
    else:
        app.run(host="0.0.0.0", port=8080)
