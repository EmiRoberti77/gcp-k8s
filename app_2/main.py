import os
import socket
from datetime import datetime, timezone
from fastapi import FastAPI

app = FastAPI(title="Kubernetes Learning API")
app_version = os.getenv("APP_VERSION", "EMI")
print(f"App Version: {app_version}")

def get_ip():
    # POD_IP can be injected via the Kubernetes Downward API; fall back to resolving the hostname
    try:
        return os.getenv("POD_IP") or socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        return "unknown"

@app.get("/")
def home():
    return {
        "message": "Hello from Kubernetes!",
        "hostname": socket.gethostname(),
        "ip": get_ip(),
        "version": app_version
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "ip": get_ip()
    }

@app.get("/time")
def get_time():
    return {
        "utc_time": datetime.now(timezone.utc).isoformat(),
        "pod": socket.gethostname(),
        "ip": get_ip()
    }
