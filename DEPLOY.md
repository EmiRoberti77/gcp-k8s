# Deploying app_2 to GKE with Cloud Build

Every push to `main` that touches `app_2/` or `cloudbuild.yaml` will:

1. Build the `app_2` Docker image
2. Push it to Artifact Registry (`europe-west2-docker.pkg.dev/emi-k8s-env/python-repo/app-2`)
3. Deploy it to the GKE Autopilot cluster `k8s-cluster`

Files involved:

| File | Purpose |
|------|---------|
| `app_2/Dockerfile` | Container image for the FastAPI app |
| `app_2/manifests/app.yaml` | Kubernetes Deployment (2 replicas) + LoadBalancer Service |
| `cloudbuild.yaml` | The pipeline: build → push → deploy |

All commands below are for **PowerShell**, run from the repo root (`C:\Users\PC\code\GCP\k8s`).
Steps 1–8 are one-time setup.

---

## 1. Log in to gcloud

```powershell
gcloud auth login
gcloud config set project emi-k8s-env
gcloud config set compute/region europe-west2
```

Set some variables used in the rest of this guide (re-run these if you open a new terminal):

```powershell
$PROJECT_ID     = "emi-k8s-env"
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$REGION         = "europe-west2"
$CLUSTER        = "k8s-cluster"
$REPO           = "python-repo"
$BUILD_SA       = "cloudbuild-deployer@$PROJECT_ID.iam.gserviceaccount.com"
```

## 2. Enable the required APIs

```powershell
gcloud services enable container.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

## 3. Artifact Registry repository

`python-repo` already exists. Only if you ever need to recreate it:

```powershell
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION --description="Python API Docker images"
```

## 4. Create the GKE Autopilot cluster

Takes ~5–10 minutes. Autopilot manages the nodes for you; you pay for the pods' requested CPU/memory.

```powershell
gcloud container clusters create-auto $CLUSTER --region=$REGION
```

Let the cluster's nodes pull images from Artifact Registry (they run as the Compute Engine default service account):

```powershell
gcloud artifacts repositories add-iam-policy-binding $REPO --location=$REGION --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role="roles/artifactregistry.reader"
```

## 5. Connect kubectl to the cluster

```powershell
gcloud components install gke-gcloud-auth-plugin
gcloud container clusters get-credentials $CLUSTER --region=$REGION
kubectl get nodes
```

`kubectl` now points at GKE. To switch back to your local kind cluster: `kubectl config use-context kind-python-lab`.

## 6. Create a service account for the pipeline

Cloud Build runs as this account. It can push images, deploy to GKE and write logs — nothing else.

```powershell
gcloud iam service-accounts create cloudbuild-deployer --display-name="Cloud Build deployer"

foreach ($role in "roles/artifactregistry.writer", "roles/container.developer", "roles/logging.logWriter") {
    gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$BUILD_SA" --role=$role --condition=None
}
```

## 7. Test the pipeline manually

Before wiring up GitHub, run the pipeline once from your machine. This uploads the repo, builds, pushes and deploys:

```powershell
gcloud builds submit --config=cloudbuild.yaml --region=$REGION --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" .
```

Then check it (see [step 9](#9-check-the-deployment)).

## 8. Connect GitHub and create the trigger

**8a. Allow Cloud Build to store the GitHub token in Secret Manager:**

```powershell
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-cloudbuild.iam.gserviceaccount.com" --role="roles/secretmanager.admin" --condition=None
```

**8b. Create the GitHub connection:**

```powershell
gcloud builds connections create github github-conn --region=$REGION
```

This prints a link. Open it, sign in to GitHub, and install the **Google Cloud Build** GitHub App on the `EmiRoberti77/gcp-k8s` repository. Then confirm the connection is ready:

```powershell
gcloud builds connections describe github-conn --region=$REGION --format="value(installationState.stage)"
```

It should say `COMPLETE`. If not, follow the `actionUri` shown by `gcloud builds connections describe github-conn --region=$REGION`.

**8c. Link the repository:**

```powershell
gcloud builds repositories create gcp-k8s --remote-uri="https://github.com/EmiRoberti77/gcp-k8s.git" --connection=github-conn --region=$REGION
```

**8d. Create the trigger** (fires on pushes to `main` that change `app_2/` or `cloudbuild.yaml`):

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

Call `/` a few times — the `hostname` and `ip` alternate between the two pods.

---

## Day-to-day: deploying a change

```powershell
git add .
git commit -m "Describe your change"
git push origin main
```

Watch the build:

```powershell
gcloud builds list --region=$REGION --limit=5
gcloud builds log --region=$REGION --stream <BUILD_ID>
```

Or in the console: **Cloud Build → History** (region `europe-west2`).

Each build tags the image with its build ID and `latest`, and the deployment is pinned to the exact image digest, so `kubectl rollout history deployment/app-2` shows each release.

## Rolling back

```powershell
kubectl rollout undo deployment/app-2
```

Or redeploy an older commit: **Cloud Build → History**, open an earlier successful build, click **Rebuild**.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Pods stuck in `ImagePullBackOff` | Re-run the Artifact Registry reader binding in step 4 |
| Build fails at `deploy` with permission denied | Check the service account roles in step 6 |
| Trigger doesn't fire | Push must be to `main` and change `app_2/**` or `cloudbuild.yaml`; check `gcloud builds triggers list --region=$REGION` |
| Pods restart repeatedly | `kubectl logs -l app=app-2` and `kubectl describe pod -l app=app-2` — usually the `/health` probe failing |

## Tearing down (to stop paying)

The cluster and load balancer cost money while running. To remove them:

```powershell
kubectl delete -f app_2/manifests/app.yaml
gcloud container clusters delete $CLUSTER --region=$REGION
```

Deleting the service first releases the load balancer. Images in Artifact Registry are kept (cheap storage); the trigger stays but its builds will fail until the cluster exists again.
