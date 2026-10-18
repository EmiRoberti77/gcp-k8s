# gcp-k8s

A small FastAPI app (`app_2`) built with Cloud Build, stored in Artifact Registry and deployed to a GKE Autopilot cluster on Google Cloud.

This README records every step taken to set up the repo, build the image and deploy it. All commands are **PowerShell**, run from the repo root (`C:\Users\PC\code\GCP\k8s`).

---

## Contents

- [Project layout](#project-layout)
- [How it fits together](#how-it-fits-together)
- [0. Git and GitHub setup](#0-git-and-github-setup)
- [1. Run the app locally](#1-run-the-app-locally)
- [2. Log in to gcloud and set variables](#2-log-in-to-gcloud-and-set-variables)
- [3. Enable the required APIs](#3-enable-the-required-apis)
- [4. Artifact Registry repository](#4-artifact-registry-repository)
- [5. Create the GKE Autopilot cluster](#5-create-the-gke-autopilot-cluster)
- [6. Connect kubectl to the cluster](#6-connect-kubectl-to-the-cluster)
- [7. Create the Cloud Build service account](#7-create-the-cloud-build-service-account)
- [8. Build, push and deploy with Cloud Build](#8-build-push-and-deploy-with-cloud-build)
- [9. Check the deployment](#9-check-the-deployment)
- [10. Automatic deploys from GitHub (not yet set up)](#10-automatic-deploys-from-github-not-yet-set-up)
- [Deploying a change](#deploying-a-change)
- [Rolling back](#rolling-back)
- [Troubleshooting](#troubleshooting)
- [Tearing down](#tearing-down)

---

## Project layout

| Path | Purpose |
|------|---------|
| `app_2/main.py` | FastAPI app with `/`, `/health` and `/time` endpoints |
| `app_2/Dockerfile` | Container image (Python 3.15 slim, runs as non-root `appuser` on port 8000) |
| `app_2/manifests/app.yaml` | Kubernetes Deployment (2 replicas) + LoadBalancer Service |
| `cloudbuild.yaml` | Cloud Build pipeline: build → push → deploy |
| `app_2/build.bat`, `app_2/run_docker.bat` | Build and run the image locally with Docker |
| `start_app_2.bat` / `start_app_2.sh` | Run the app locally without Docker |
| `app_1/` | Earlier version of the app; not deployed |
| `app_1/k8s/*.yml` | Bruno API client requests, not Kubernetes manifests |
| `.env` | Local environment variables (`APP_VERSION`); git-ignored |

### The app

| Endpoint | Returns |
|----------|---------|
| `GET /` | Message, pod hostname, pod IP, app version |
| `GET /health` | `{"status": "healthy", "ip": ...}`, used by the Kubernetes probes |
| `GET /time` | Current UTC time, pod hostname and IP |

The pod IP comes from the `POD_IP` environment variable, which the manifest injects through the Kubernetes Downward API.

## How it fits together

```
 your machine / GitHub
          │  gcloud builds submit   (or a push to main, once step 10 is done)
          ▼
 Cloud Build  (runs as cloudbuild-deployer)
   1. build   docker build app_2
   2. push    → europe-west2-docker.pkg.dev/emi-k8s-env/python-repo/app-2:<BUILD_ID> and :latest
   3. deploy  gke-deploy applies app_2/manifests to k8s-cluster, pinned to the new image
          ▼
 GKE Autopilot cluster k8s-cluster (europe-west2)
   Deployment app-2   2 pods, probes on /health
   Service    app-2   LoadBalancer, port 80 → 8000
          ▼
 http://<EXTERNAL-IP>/
```

| Resource | Value |
|----------|-------|
| GCP project | `emi-k8s-env` (number `1072896640779`) |
| Region | `europe-west2` |
| Artifact Registry repo | `python-repo` |
| Image | `europe-west2-docker.pkg.dev/emi-k8s-env/python-repo/app-2` |
| GKE cluster | `k8s-cluster` (Autopilot) |
| Build service account | `cloudbuild-deployer@emi-k8s-env.iam.gserviceaccount.com` |
| Kubernetes Deployment / Service | `app-2` / `app-2` |

---

## 0. Git and GitHub setup

Git for Windows was already installed at `C:\Program Files\Git`. If `git` isn't found, open a new terminal so it picks up the updated `PATH`.

```powershell
git config --global user.name "EmiRoberti77"
git config --global user.email "emiroberti@icloud.com"

git init -b main
git remote add origin https://github.com/EmiRoberti77/gcp-k8s.git
```

A `.gitignore` keeps secrets and local files out of the repo:

```
.env
.venv/
__pycache__/
*.pyc
```

First commit and push:

```powershell
git add .
git commit -m "Initial commit"
git push -u origin main
```

The first push opens a browser window to sign in to GitHub; Git Credential Manager remembers the login after that.

## 1. Run the app locally

Without Docker (uses the project's `.venv`):

```powershell
uvicorn app_2.main:app --host 0.0.0.0 --port 8000
```

With Docker (Docker Desktop must be running):

```powershell
cd app_2
docker build -t app_2 .
docker run --rm -p 8000:8000 --env-file ..\.env app_2
```

Then open http://localhost:8000.

## 2. Log in to gcloud and set variables

```powershell
gcloud auth login
gcloud config set project emi-k8s-env
gcloud config set compute/region europe-west2
```

Set the variables used in the rest of this guide. Run these again whenever you open a new terminal:

```powershell
$PROJECT_ID     = "emi-k8s-env"
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$REGION         = "europe-west2"
$CLUSTER        = "k8s-cluster"
$REPO           = "python-repo"
$BUILD_SA       = "cloudbuild-deployer@$PROJECT_ID.iam.gserviceaccount.com"
```

## 3. Enable the required APIs

```powershell
gcloud services enable container.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

## 4. Artifact Registry repository

The Docker repository `python-repo` already existed in `europe-west2`, so it was reused. To recreate it if needed:

```powershell
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION --description="Python API Docker images"
```

## 5. Create the GKE Autopilot cluster

This takes about 5–10 minutes. Autopilot manages the nodes, and you pay for the CPU and memory the pods request.

```powershell
gcloud container clusters create-auto $CLUSTER --region=$REGION
```

Let the cluster's nodes pull images from Artifact Registry. The nodes run as the Compute Engine default service account:

```powershell
gcloud artifacts repositories add-iam-policy-binding $REPO --location=$REGION --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role="roles/artifactregistry.reader"
```

## 6. Connect kubectl to the cluster

```powershell
gcloud components install gke-gcloud-auth-plugin
gcloud container clusters get-credentials $CLUSTER --region=$REGION
kubectl get nodes
```

An Autopilot cluster may show no nodes until something is deployed; that's normal.

`kubectl` now points at GKE (context `gke_emi-k8s-env_europe-west2_k8s-cluster`). To switch back to the local kind cluster:

```powershell
kubectl config use-context kind-python-lab
```

## 7. Create the Cloud Build service account

Cloud Build runs the pipeline as this account. It has only the permissions the pipeline needs.

```powershell
gcloud iam service-accounts create cloudbuild-deployer --display-name="Cloud Build deployer"

foreach ($role in "roles/artifactregistry.writer", "roles/container.developer", "roles/logging.logWriter") {
    gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$BUILD_SA" --role=$role --condition=None
}
```

| Role | Why |
|------|-----|
| `roles/artifactregistry.writer` | Push the built image |
| `roles/container.developer` | Apply the manifests to the cluster |
| `roles/logging.logWriter` | Write build logs (`cloudbuild.yaml` uses `CLOUD_LOGGING_ONLY`) |

The account also needs to read the source code that `gcloud builds submit` uploads to the `emi-k8s-env_cloudbuild` bucket. Without this permission the build fails with `does not have storage.objects.get access`:

```powershell
gcloud storage buckets add-iam-policy-binding gs://emi-k8s-env_cloudbuild --member="serviceAccount:$BUILD_SA" --role="roles/storage.objectViewer"
```

> The bucket is created automatically the first time `gcloud builds submit` runs. If it doesn't exist yet, run step 8 once, which will fail with the 403 error, then add this binding and run step 8 again.

## 8. Build, push and deploy with Cloud Build

```powershell
gcloud builds submit --config=cloudbuild.yaml --region=$REGION --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" .
```

This uploads the repo (respecting `.gitignore`, so `.env` and `.venv` stay local) and runs the three steps in `cloudbuild.yaml`:

1. **build**: `docker build app_2`, tagged `app-2:<BUILD_ID>` and `app-2:latest`
2. **push**: pushes both tags to `python-repo`
3. **deploy**: `gke-deploy` applies `app_2/manifests/` to `k8s-cluster`, replacing the image in `app.yaml` with the exact digest just built

The values in `cloudbuild.yaml` (`_REGION`, `_CLUSTER`, `_REPO`, `_IMAGE`) can be overridden with `--substitutions=_CLUSTER=other-cluster,...`.

## 9. Check the deployment

```powershell
kubectl get pods -l app=app-2 -o wide
kubectl get service app-2
```

Wait until the service's `EXTERNAL-IP` changes from `<pending>` to an address (1–2 minutes), then:

```powershell
$IP = kubectl get service app-2 -o jsonpath="{.status.loadBalancer.ingress[0].ip}"
curl.exe "http://$IP/"
curl.exe "http://$IP/health"
curl.exe "http://$IP/time"
```

Example response:

```json
{"message":"Hello from Kubernetes!","hostname":"app-2-75b6ddf9f6-99v2b","ip":"10.127.0.16","version":"v2"}
```

Call `/` a few times. The `hostname` and `ip` alternate between the two pods as the load balancer spreads requests.

---

## 10. Automatic deploys from GitHub (not yet set up)

Once this step is done, every push to `main` that changes `app_2/` or `cloudbuild.yaml` runs the pipeline automatically.

**10a. Commit and push the pipeline files.** The trigger builds from GitHub, not from your machine, so `cloudbuild.yaml`, `app_2/manifests/` and the updated `app_2/Dockerfile` must be on `main`:

```powershell
git add .
git commit -m "Add Cloud Build pipeline and k8s manifests for app_2"
git push
```

**10b. Allow Cloud Build to store the GitHub token in Secret Manager:**

```powershell
gcloud services enable secretmanager.googleapis.com
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-cloudbuild.iam.gserviceaccount.com" --role="roles/secretmanager.admin" --condition=None
```

**10c. Create the GitHub connection:**

```powershell
gcloud builds connections create github github-conn --region=$REGION
```

Open the printed link, sign in to GitHub and install the **Google Cloud Build** GitHub App on `EmiRoberti77/gcp-k8s`. Then check the connection:

```powershell
gcloud builds connections describe github-conn --region=$REGION --format="value(installationState.stage)"
```

It should say `COMPLETE`.

**10d. Link the repository:**

```powershell
gcloud builds repositories create gcp-k8s --remote-uri="https://github.com/EmiRoberti77/gcp-k8s.git" --connection=github-conn --region=$REGION
```

**10e. Create the trigger:**

```powershell
gcloud builds triggers create github `
  --name=app-2-deploy `
  --region=$REGION `
  --repository="projects/$PROJECT_ID/locations/$REGION/connections/github-conn/repositories/gcp-k8s" `
  --branch-pattern="^main$" `
  --build-config=cloudbuild.yaml `
  --included-files="app_2/**,cloudbuild.yaml" `
  --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA"
```

Triggered builds read source directly from GitHub, so the bucket permission from step 7 isn't needed for them, but it does no harm.

---

## Deploying a change

**With the trigger (step 10 done):**

```powershell
git add .
git commit -m "Describe your change"
git push
```

**Without the trigger:** run the `gcloud builds submit` command from [step 8](#8-build-push-and-deploy-with-cloud-build).

Watch builds:

```powershell
gcloud builds list --region=$REGION --limit=5
gcloud builds log --region=$REGION --stream <BUILD_ID>
```

Or in the console: **Cloud Build → History** (region `europe-west2`).

Every build tags the image with its build ID, and the Deployment is pinned to the exact image digest, so `kubectl rollout history deployment/app-2` lists each release.

## Rolling back

```powershell
kubectl rollout undo deployment/app-2
kubectl rollout status deployment/app-2
```

Or open an earlier successful build in **Cloud Build → History** and click **Rebuild**.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `git` not recognised | Open a new terminal, or use `"C:\Program Files\Git\cmd\git.exe"` |
| `git push`: `terminal prompts disabled` | Run the push from an interactive terminal so the GitHub sign-in window can open |
| Build fails: `does not have storage.objects.get access` | Add the `roles/storage.objectViewer` bucket binding from step 7 |
| Build fails at `deploy` with permission denied | Check the service account roles in step 7 |
| Pods stuck in `ImagePullBackOff` | Re-run the Artifact Registry reader binding in step 5 |
| Pods restart repeatedly | `kubectl logs -l app=app-2` and `kubectl describe pod -l app=app-2`; usually the `/health` probe failing |
| `EXTERNAL-IP` stays `<pending>` | Wait a few minutes; check `kubectl describe service app-2` for events |
| `kubectl` talks to the wrong cluster | `kubectl config current-context`; switch with `kubectl config use-context <name>` |
| Trigger doesn't fire | Push must be to `main` and change `app_2/**` or `cloudbuild.yaml`; check `gcloud builds triggers list --region=$REGION` |

## Tearing down

The cluster and the load balancer cost money while they exist. To remove them:

```powershell
kubectl delete -f app_2/manifests/app.yaml
gcloud container clusters delete $CLUSTER --region=$REGION
```

Delete the Service first so the load balancer is released. Images in Artifact Registry are kept, since storage is cheap. If the trigger exists, its builds will fail until the cluster is recreated.
