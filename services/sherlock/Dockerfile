# Build from the repository root:
#   docker build -f services/sherlock/Dockerfile -t deepsift/svc-sherlock .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/sherlock /app/services/sherlock
RUN pip install --no-cache-dir /app/sdk /app/services/sherlock \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_sherlock:SherlockService"]
