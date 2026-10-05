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

def classify_pod(pod):
    """Classify a pod into one of 'db', 'web', 'worker', or None (unknown)."""
    labels = pod.metadata.labels or {}
    app_label = labels.get("app", "")
    k8s_app_label = labels.get("app.kubernetes.io/name", "")
    name = pod.metadata.name or ""

    if name.startswith("db-") or "postgresql" in k8s_app_label or "postgres" in app_label:
        return "db"
    elif "worker" in app_label:
        return "worker"
    elif "web" in app_label:
        return "web"
    return None

def get_pod_summary():
    """Return a summary of ready pod counts vs. expected replica counts for
    the db, web, and worker groups.

    The "expected" total is read directly from the owning Deployment's
    (web/worker) or StatefulSet's (db-) replica spec, rather than from the
    number of pods currently found, so that missing/crashed pods correctly
    show up as a shortfall (e.g. 2/3) instead of silently shrinking the
    total.
    """
    summary = {
        "db": {"label": "Database (db-)", "ready": 0, "total": 0},
        "web": {"label": "Web Service", "ready": 0, "total": 0},
        "worker": {"label": "Workers", "ready": 0, "total": 0},
    }
    # Fallback counts, used only if we can't read the Deployment/StatefulSet specs
    pods_found = {"db": 0, "web": 0, "worker": 0}
    error = None
    try:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        namespace = get_namespace()

        # Expected replicas for web/worker come from their Deployments.
        try:
            deployments = apps_v1.list_namespaced_deployment(namespace)
            for dep in deployments.items:
                name = dep.metadata.name or ""
                replicas = dep.spec.replicas or 0
                if name.endswith("-web"):
                    summary["web"]["total"] = replicas
                elif name.endswith("-worker"):
                    summary["worker"]["total"] = replicas
        except Exception:
            pass

        # Expected replicas for the db- pods come from their StatefulSet(s).
        try:
            statefulsets = apps_v1.list_namespaced_stateful_set(namespace)
            for sts in statefulsets.items:
                name = sts.metadata.name or ""
                if name.startswith("db"):
                    summary["db"]["total"] += sts.spec.replicas or 0
        except Exception:
            pass

        pod_list = v1.list_namespaced_pod(namespace)
        
        for pod in pod_list.items:
            category = classify_pod(pod)
            if category is None:
                continue

            ready = False
            if pod.status.container_statuses:
                ready = all(cs.ready for cs in pod.status.container_statuses)

            pods_found[category] += 1
            if ready:
                summary[category]["ready"] += 1

        # Fall back to the number of pods actually found if we couldn't
        # determine the expected replica count (e.g. missing RBAC permissions
        # on deployments/statefulsets).
        for key in summary:
            if summary[key]["total"] == 0 and pods_found[key] > 0:
                summary[key]["total"] = pods_found[key]
    except Exception as e:
        error = str(e)

    return summary, error

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
        .squares { display: flex; gap: 20px; flex-wrap: wrap; }
        .square {
            width: 160px;
            height: 160px;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: white;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.15);
        }
        .square.healthy { background-color: #28a745; }
        .square.unhealthy { background-color: #dc3545; }
        .square .count { font-size: 2.2em; font-weight: bold; }
        .square .label { font-size: 1em; margin-top: 10px; }
        .pod-error { color: red; margin-top: 10px; }
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
        <div class="squares">
            {% for key in ['db', 'web', 'worker'] %}
            {% set info = pods[key] %}
            <div class="square {{ 'healthy' if info.total > 0 and info.ready == info.total else 'unhealthy' }}">
                <div class="count">{{ info.ready }} / {{ info.total }}</div>
                <div class="label">{{ info.label }}</div>
            </div>
            {% endfor %}
        </div>
        {% if pod_error %}
        <p class="pod-error">Error querying Kubernetes API: {{ pod_error }}</p>
        {% endif %}
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

    pods, pod_error = get_pod_summary()
    return render_template_string(HTML_TEMPLATE, last_ts=last_ts, stats=stats, pods=pods, pod_error=pod_error)

def run_worker():
    print("Starting worker process...", flush=True)
    heartbeat_file = "/tmp/worker_heartbeat"

    # Touch heartbeat file immediately on startup so probes pass during initialization
    try:
        with open(heartbeat_file, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        print(f"Error creating initial heartbeat file: {e}", flush=True)

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

            # Update heartbeat timestamp file on successful DB write
            with open(heartbeat_file, "w") as f:
                f.write(str(time.time()))
            print("Keepalive written successfully.", flush=True)
        except Exception as e:
            print(f"Error writing to DB: {e}", flush=True)

        time.sleep(60)

if __name__ == "__main__":
    mode = os.getenv("APP_MODE", "web")
    if mode == "worker":
        run_worker()
    else:
        app.run(host="0.0.0.0", port=8080)
