# Build from the repository root:
#   docker build -f gateway/Dockerfile -t deepsift/gateway .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DEEPSIFT_HOST=0.0.0.0 DEEPSIFT_PORT=8000 DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY sdk /app/sdk
COPY gateway /app/gateway
RUN pip install --no-cache-dir /app/sdk /app/gateway \
    && useradd --system --no-create-home deepsift \
    && mkdir -p /data/blobs && chown -R deepsift /data

USER deepsift
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]
CMD ["deepsift-gateway"]
