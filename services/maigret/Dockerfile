# Build from the repository root:
#   docker build -f services/maigret/Dockerfile -t deepsift/svc-maigret .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/maigret /app/services/maigret
RUN pip install --no-cache-dir /app/sdk /app/services/maigret \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_maigret:MaigretService"]
