# Build from the repository root:
#   docker build -f services/tineye/Dockerfile -t deepsift/svc-tineye .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY sdk /app/sdk
COPY services/tineye /app/services/tineye
RUN pip install --no-cache-dir /app/sdk /app/services/tineye \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_tineye:TinEyeService"]
