FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Versions match uv.lock at the repo root
RUN pip install --no-cache-dir \
    "fastapi==0.143.3" \
    "uvicorn==0.54.0"

COPY main.py .

RUN useradd --create-home --uid 1000 appuser
USER appuser

ENV APP_VERSION=v2

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
