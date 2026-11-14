# Build from the repository root:
#   docker build -f services/searxng/Dockerfile -t deepsift/svc-searxng .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/searxng /app/services/searxng
RUN pip install --no-cache-dir /app/sdk /app/services/searxng \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_searxng:SearxngService"]
