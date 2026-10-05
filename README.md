
# Highly Available Keepalive Demo on Canonical Kubernetes

This repository contains a complete, production-grade demo application designed for Canonical Kubernetes (MicroK8s or Charmed K8s). It features a Python worker that writes a timestamp to PostgreSQL every minute, a 3-replica web frontend displaying keepalive stats and live pod health statuses, and strict Cilium Network Policies to secure pod-to-pod and external traffic.

---

## Architecture Overview


```

```
                      [ External Clients / VIP ]
                                  │
                         (LoadBalancer: Port 80)
                                  │
                 ┌────────────────┴────────────────┐
                 │ Cilium L7 Network Policy Filter │
                 │   (Allows ONLY GET / HTTP)      │
                 └────────────────┬────────────────┘
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
             [ Web Pod 1 ]   [ Web Pod 2 ]   [ Web Pod 3 ]
                  │               │               │
                  └───────────────┼───────────────┘
                                  │ (TCP 5432)
                                  ├────────────────────────┐
                                  ▼                        │
                     [ Charmed PostgreSQL K8s ]           │
                     │ 3-Unit HA Patroni Cluster │          │
                     │ Storage: CephXFS PVCs    │          │
                     └────────────▲─────────────┘          │
                                  │ (TCP 5432)             │
                            [ Worker Pod ] ────────────────┘
                        (Ubuntu 26.04 Base)
                   (Writes timestamp every 60s)

```

```

### Key Components

* **Frontend Web Application**: Python (Flask) running 3 replicas behind a Kubernetes `LoadBalancer` Service. Auto-refreshes every 60 seconds and queries the Kubernetes API Server for live pod health.
* **Worker Service**: Singleton Python background worker based on **Ubuntu 26.04** using **`psycopg` (v3)** to insert timestamps every minute.
* **Database**: **Canonical Charmed PostgreSQL K8s** deployed via Juju in a 3-unit HA topology with automatic failover, backed by **CephXFS** persistent storage.
* **Network Security**: **Cilium Network Policies** enforcing L7 HTTP filtering (`GET /` allowed; all other HTTP methods and paths rejected with `403 Forbidden`) and egress/ingress isolation on database ports.

---

## Prerequisites

Ensure you have the following installed and configured on your management machine/cluster:

* **Canonical Kubernetes Cluster** (MicroK8s or Charmed K8s) with **Cilium CNI** enabled.
* **Juju CLI** configured and bootstrapped on the cluster.
* **Helm v3** installed.
* **Docker** or **Containerd CLI** for container builds.
* An accessible Container Registry (e.g., Docker Hub, Harbor, or MicroK8s built-in registry).
* A pre-existing **CephXFS** StorageClass configured in Kubernetes.

---

## Project Structure

```text
keepalive-demo/
├── Dockerfile
├── requirements.txt
├── app.py
├── Chart.yaml
├── values.yaml
└── templates/
    ├── db-secret.yaml
    ├── web-deployment.yaml
    ├── web-service.yaml
    ├── web-rbac.yaml
    ├── worker-deployment.yaml
    ├── cilium-policy-web.yaml
    ├── cilium-policy-worker.yaml
    └── cilium-policy-db.yaml

```

---

## Step-by-Step Installation Guide

### Step 1: Build and Push Container Image

1. Build the application container image using the Ubuntu 26.04 base Dockerfile:
```bash
docker build -t your-registry/keepalive-demo:1.0.0 .

```


2. Push the image to your container registry:
```bash
docker push your-registry/keepalive-demo:1.0.0

```



---

### Step 2: Deploy HA Charmed PostgreSQL via Juju

1. Create a new Juju model named `keepalive` (this also creates the corresponding Kubernetes namespace):
```bash
juju add-model keepalive

```


2. Deploy 3 units of Charmed PostgreSQL K8s backed by `cephxfs` storage:
```bash
juju deploy postgresql-k8s db -n 3 --channel 14/stable --storage pgdata=cephxfs,10G

```


3. Deploy the `data-integrator` charm to provision the `keepalivedb` database and application user credentials:
```bash
juju deploy data-integrator app-db-credentials --config database-name=keepalivedb
juju integrate app-db-credentials db

```


4. Wait until the database units reach `active/idle` status:
```bash
juju status --watch 2s

```


5. Retrieve the auto-generated database credentials:
```bash
juju run app-db-credentials/leader get-credentials

```


*Take note of the `username` and `password` values returned by Juju.*

---

### Step 3: Deploy the Application with Helm

1. Update `values.yaml` with your image repository (the `tag` defaults to the value in `values.yaml`, but is typically overridden per-deployment, see step 2):
```yaml
app:
  repository: "your-registry/keepalive-demo"
  tag: "1.0.0"

```


2. Deploy the Helm release into the `keepalive` namespace, injecting the Juju DB credentials and the desired image tag:
```bash
helm upgrade --install my-keepalive-demo ./keepalive-demo \
  -n keepalive \
  --set db.username="<USERNAME_FROM_JUJU>" \
  --set db.password="<PASSWORD_FROM_JUJU>" \
  --set app.tag="1.0.0"

```

> To roll out a new image build later, simply re-run `helm upgrade` with a different `--set app.tag=<new-tag>` without touching `values.yaml`.


3. Verify all pods are running and ready:
```bash
kubectl get pods -n keepalive

```



---

## Accessing the Dashboard

1. Retrieve the external LoadBalancer IP assigned to the frontend:
```bash
EXTERNAL_IP=$(kubectl get svc my-keepalive-demo-web-svc -n keepalive -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Access Dashboard at: http://${EXTERNAL_IP}/"

```


2. Open `http://${EXTERNAL_IP}/` in your browser. The dashboard displays:
* **Last Timestamp Registered**: The latest keepalive message written by the worker.
* **Pods Status Table**: Real-time status of Web, Worker, and Charmed PostgreSQL pods queried directly from the Kubernetes API.
* **Keepalive Messages Table**: Historical count of keepalives grouped by minute.
* **Auto-refresh**: The page refreshes automatically every 60 seconds.



---

## Testing Cilium Network Policies

The chart includes three CiliumNetworkPolicy manifests (`cilium-policy-web`, `cilium-policy-worker`, and `cilium-policy-db`).

### 1. Test Layer 7 HTTP Filtering on Web Frontend

The web policy permits **only** `GET` requests to the root path (`/`). All other HTTP methods or unapproved routes must be blocked by Cilium's Envoy proxy.

```bash
# 1. Allowed: GET request to root path -> Returns 200 OK
curl -i -X GET http://${EXTERNAL_IP}/

# 2. Denied: POST request to root path -> Returns 403 Access Denied
curl -i -X POST http://${EXTERNAL_IP}/

# 3. Denied: DELETE request to root path -> Returns 403 Access Denied
curl -i -X DELETE http://${EXTERNAL_IP}/

# 4. Denied: GET request to unapproved route -> Returns 403 Access Denied
curl -i -X GET http://${EXTERNAL_IP}/admin

```

### 2. Test Isolation on Database Pods

PostgreSQL accepts incoming TCP connections on port 5432 **only** from pods labeled `app=my-keepalive-demo-web` or `app=my-keepalive-demo-worker`.

To verify database isolation, spawn an unauthorized pod in the same namespace and attempt to reach the database:

```bash
# Attempt direct connection from an unauthorized pod -> Connection times out
kubectl run unauthorized-test --rm -it --namespace keepalive \
  --image=alpine -- nc -zv -w 3 db-primary.keepalive.svc.cluster.local 5432

```

### 3. Observe Traffic Drops in Real-Time

Use the Hubble CLI to inspect Cilium policy enforcement:

```bash
hubble observe --namespace keepalive --verdict DROPPED -f

```

---

## Testing High Availability & Redundancy

### 1. Web Frontend Redundancy

The frontend runs across 3 replicas behind a LoadBalancer service (`externalTrafficPolicy: Local`).

1. Delete two of the web pods simultaneously:
```bash
kubectl delete pod -l app=my-keepalive-demo-web -n keepalive --grace-period=0 --force

```


2. Immediately curl the LoadBalancer IP:
```bash
curl -i http://${EXTERNAL_IP}/

```


**Expected Result**: The site stays responsive without dropping connections because remaining web pods handle incoming traffic while Deployment controllers recreate failed pods.

---

### 2. Database High Availability (Primary Failover)

Charmed PostgreSQL maintains a 3-unit Patroni cluster with automatic leader election.

1. Identify the current primary database unit:
```bash
juju status db

```


2. Trigger an intentional primary switchover or force-delete the primary pod (e.g., `db-0`):
```bash
kubectl delete pod db-0 -n keepalive --grace-period=0 --force

```


3. Watch Patroni automatically promote one of the standby units to primary:
```bash
kubectl get pods -n keepalive -w

```


4. Observe application behavior:
* The `worker` pod reconnects automatically on its next 60-second loop.
* The `web` frontend continues operating without loss of historical data once the new primary accepts connections.



---

### 3. Worker Resilience

The worker runs as a single-replica Deployment writing keepalive records every minute.

1. Delete the worker pod:
```bash
kubectl delete pod -l app=my-keepalive-demo-worker -n keepalive

```


2. Kubernetes immediately schedules a replacement worker pod. Check the dashboard after 60 seconds to confirm that new keepalive records continue updating smoothly without data gaps or duplicate keys.

---

## Cleanup

To completely uninstall the demo application and database resources:

```bash
# 1. Uninstall Helm release
helm uninstall my-keepalive-demo -n keepalive

# 2. Destroy Juju model and underlying storage PVCs
juju destroy-model keepalive --destroy-storage --yes

```

