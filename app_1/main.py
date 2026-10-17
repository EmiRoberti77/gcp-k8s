
import os
import socket
from datetime import datetime, timezone
from fastapi import FastAPI

app = FastAPI(title="Kubernetes Learning API")

@app.get("/")
def home():
    return {
        "message": "Hello from Kubernetes!",
        "hostname": socket.gethostname(),
        "version": os.getenv("APP_VERSION", "v1")
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/time")
def get_time():
    return {
        "utc_time": datetime.now(timezone.utc).isoformat(),
        "pod": socket.gethostname()
    }
