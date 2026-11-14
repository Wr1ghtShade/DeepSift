# Build from the repository root:
#   docker build -f services/avatar-hash/Dockerfile -t deepsift/svc-avatar-hash .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY sdk /app/sdk
COPY services/avatar-hash /app/services/avatar-hash
RUN pip install --no-cache-dir /app/sdk /app/services/avatar-hash \
    && useradd --system --no-create-home deepsift \
    && mkdir -p /data && chown deepsift /data

USER deepsift
VOLUME ["/data"]
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_avatar_hash:AvatarHashService"]
