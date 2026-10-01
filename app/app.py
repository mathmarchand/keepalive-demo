import os, time, psycopg2
from flask import Flask, render_template_string

app = Flask(__name__)

# Environment variables injected by Kubernetes
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "keepalivedb")

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Keepalive Dashboard</title></head>
<body style="font-family: Arial, sans-serif; margin: 40px;">
    <h2>Keepalive Status Dashboard</h2>
    <div style="background-color: #f4f4f4; padding: 15px; border-radius: 5px;">
        <strong>Last Timestamp Registered:</strong> <span style="color: blue;">{{ last_ts }}</span>
    </div>
    
    <h3>Messages Registered Per Minute</h3>
    <table border="1" cellpadding="8" cellspacing="0">
        <tr style="background-color: #ddd;">
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
</body>
</html>
"""

@app.route("/")
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Get last timestamp
        cur.execute("SELECT MAX(ts) FROM keepalives;")
        last_ts = cur.fetchone()[0]
        
        # Get count per minute
        cur.execute("""
            SELECT date_trunc('minute', ts) as minute, count(*) 
            FROM keepalives 
            GROUP BY minute 
            ORDER BY minute DESC LIMIT 20;
        """)
        stats = cur.fetchall()
        conn.close()
        return render_template_string(HTML_TEMPLATE, last_ts=last_ts, stats=stats)
    except Exception as e:
        return f"Database not ready or error occurred: {e}", 500

def run_worker():
    print("Starting worker process...")
    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # Initialize table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS keepalives (
                    id SERIAL PRIMARY KEY,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Insert keepalive
            cur.execute("INSERT INTO keepalives (ts) VALUES (NOW());")
            conn.commit()
            cur.close()
            conn.close()
            print("Keepalive written successfully.")
        except Exception as e:
            print(f"Error writing to DB: {e}")
        
        # Wait 60 seconds before next write
        time.sleep(60)

if __name__ == "__main__":
    mode = os.getenv("APP_MODE", "web")
    if mode == "worker":
        run_worker()
    else:
        app.run(host="0.0.0.0", port=8080)
