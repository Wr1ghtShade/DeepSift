# Build from the repository root:
#   docker build -f services/telegram/Dockerfile -t deepsift/svc-telegram .
# Log the dedicated account in once, then start the worker:
#   docker compose --profile telegram run --rm svc-telegram deepsift-telegram login
#   docker compose --profile telegram up -d svc-telegram
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY sdk /app/sdk
COPY services/telegram /app/services/telegram
RUN pip install --no-cache-dir /app/sdk /app/services/telegram \
    && useradd --system --no-create-home deepsift \
    && mkdir -p /data && chown deepsift /data

USER deepsift
VOLUME ["/data"]
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_telegram:TelegramService"]
