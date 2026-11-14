# Build from the repository root:
#   docker build -f services/tineye/Dockerfile -t deepsift/svc-tineye .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY sdk /app/sdk
COPY services/tineye /app/services/tineye
RUN pip install --no-cache-dir /app/sdk /app/services/tineye \
    && groupadd --system --gid 10001 deepsift \
    && useradd --system --no-create-home --uid 10001 --gid 10001 deepsift \
    && mkdir -p /data/blobs && chown -R deepsift /data

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_tineye:TinEyeService"]
