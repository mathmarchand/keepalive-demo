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

# Canonical Vanilla Framework v3.0.0, served from Canonical's asset CDN.
# The stylesheet is fetched by the end user's browser (not by the pod), so the
# web pod's Cilium egress policy does not need to allow it.
VANILLA_CSS_URL = os.getenv(
    "VANILLA_CSS_URL",
    "https://assets.ubuntu.com/v1/vanilla-framework-version-3.0.0.min.css",
)

# Canonical "Circle of Friends" logo (white), the same asset used in the
# canonical.com header. Also fetched by the browser, not the pod.
CANONICAL_LOGO_URL = os.getenv(
    "CANONICAL_LOGO_URL",
    "https://assets.ubuntu.com/v1/82818827-CoF_white.svg",
)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="60">
    <title>Keepalive Dashboard</title>
    <link rel="stylesheet" href="{{ vanilla_css_url }}">
    <style>
        /* Status tiles: Vanilla p-card coloured with Vanilla's
           positive (#0e8420) and negative (#c7162b) palette colours. */
        .status-tile {
            color: #fff;
            text-align: center;
            border: 0;
            min-height: 10rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .status-tile.is-healthy { background-color: #0e8420; }
        .status-tile.is-unhealthy { background-color: #c7162b; }
        .status-tile__count {
            font-size: 3rem;
            font-weight: 300;
            line-height: 1.2;
            margin: 0;
            padding: 0;
        }
        .status-tile__label {
            margin: 0;
            padding: 0;
        }

        /* Header brand: Canonical orange tag with the white Circle of Friends
           logo, followed by the plain-text page title (no link, as in the
           canonical.com header). Vanilla 3.0.0 has no tagged-logo component,
           so it is styled here. */
        .brand {
            display: flex;
            align-items: flex-start;
        }
        .brand__tag {
            background-color: #e95420;
            display: flex;
            align-items: flex-end;
            justify-content: center;
            width: 2rem;
            height: 3rem;
            padding-bottom: 0.4rem;
            margin-right: 0.75rem;
            flex-shrink: 0;
        }
        .brand__logo {
            width: 1.25rem;
            height: auto;
            display: block;
        }
        .brand__title {
            color: #fff;
            margin: 0;
            padding: 0.75rem 0 0;
            font-size: 1rem;
            line-height: 1.5rem;
            font-weight: 400;
        }
    </style>
</head>
<body>
    <header class="p-navigation is-dark">
        <div class="p-navigation__row">
            <div class="p-navigation__banner">
                <div class="brand">
                    <div class="brand__tag">
                        <img class="brand__logo" src="{{ canonical_logo_url }}" alt="Canonical">
                    </div>
                    <h1 class="brand__title">Keepalive Status Dashboard</h1>
                </div>
            </div>
        </div>
    </header>

    <main>
        <section class="p-strip is-shallow">
            <div class="row">
                <div class="col-12">
                    <p class="p-text--small u-text--muted">Auto-refreshing every 60 seconds</p>

                    {% if db_error %}
                    <div class="p-notification--negative">
                        <div class="p-notification__content">
                            <h5 class="p-notification__title">Database error</h5>
                            <p class="p-notification__message">{{ db_error }}</p>
                        </div>
                    </div>
                    {% endif %}

                    {% if pod_error %}
                    <div class="p-notification--negative">
                        <div class="p-notification__content">
                            <h5 class="p-notification__title">Kubernetes API error</h5>
                            <p class="p-notification__message">{{ pod_error }}</p>
                        </div>
                    </div>
                    {% endif %}

                    <div class="p-card">
                        <h4 class="p-muted-heading">Last registered timestamp in DB</h4>
                        <p class="p-heading--3 u-no-margin--bottom">{{ last_ts }}</p>
                    </div>
                </div>
            </div>
        </section>

        <section class="p-strip is-shallow u-no-padding--top">
            <div class="row">
                <div class="col-12">
                    <h2 class="p-heading--4">Pods status</h2>
                </div>
            </div>
            <div class="row">
                {% for key in ['db', 'web', 'worker'] %}
                {% set info = pods[key] %}
                {% set healthy = info.total > 0 and info.ready == info.total %}
                <div class="col-4">
                    <div class="p-card status-tile {{ 'is-healthy' if healthy else 'is-unhealthy' }}">
                        <p class="status-tile__count">{{ info.ready }} / {{ info.total }}</p>
                        <p class="status-tile__label">{{ info.label }}</p>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>

        <section class="p-strip is-shallow u-no-padding--top">
            <div class="row">
                <div class="col-12">
                    <h2 class="p-heading--4">Keepalive messages registered per minute</h2>
                    <table class="p-table--mobile-card" aria-label="Keepalive messages per minute">
                        <thead>
                            <tr>
                                <th>Minute</th>
                                <th class="u-align--right">Keepalive count</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in stats %}
                            <tr>
                                <td data-heading="Minute">{{ row[0] }}</td>
                                <td data-heading="Keepalive count" class="u-align--right">{{ row[1] }}</td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="2" class="u-text--muted">No keepalive data available</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    </main>
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
        last_ts = "Unavailable"
        stats = []
        db_error = str(e)
    else:
        db_error = None

    pods, pod_error = get_pod_summary()
    return render_template_string(
        HTML_TEMPLATE,
        vanilla_css_url=VANILLA_CSS_URL,
        canonical_logo_url=CANONICAL_LOGO_URL,
        last_ts=last_ts,
        stats=stats,
        pods=pods,
        pod_error=pod_error,
        db_error=db_error,
    )

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

def run_cleanup():
    """Delete keepalive rows older than RETENTION_HOURS (default 24), then exit.

    Intended to be run as a Kubernetes CronJob. Exits non-zero on failure so
    the Job is marked as failed and retried according to its backoffLimit.
    """
    retention_hours = int(os.getenv("RETENTION_HOURS", "24"))
    print(f"Starting cleanup: deleting keepalives older than {retention_hours}h...", flush=True)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('keepalives');")
                if cur.fetchone()[0] is None:
                    print("Table 'keepalives' does not exist yet, nothing to clean.", flush=True)
                    return
                cur.execute(
                    "DELETE FROM keepalives WHERE ts < NOW() - make_interval(hours => %s);",
                    (retention_hours,),
                )
                deleted = cur.rowcount
            conn.commit()
        print(f"Cleanup complete: {deleted} row(s) deleted.", flush=True)
    except Exception as e:
        print(f"Error during cleanup: {e}", flush=True)
        raise SystemExit(1)

if __name__ == "__main__":
    mode = os.getenv("APP_MODE", "web")
    if mode == "worker":
        run_worker()
    elif mode == "cleanup":
        run_cleanup()
    else:
        app.run(host="0.0.0.0", port=8080)
