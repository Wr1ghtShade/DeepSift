# Build from the repository root:
#   docker build -f services/holehe/Dockerfile -t deepsift/svc-holehe .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/holehe /app/services/holehe
RUN pip install --no-cache-dir /app/sdk /app/services/holehe \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_holehe:HoleheService"]
