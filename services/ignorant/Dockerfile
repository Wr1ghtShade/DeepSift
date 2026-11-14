# Build from the repository root:
#   docker build -f services/ignorant/Dockerfile -t deepsift/svc-ignorant .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/ignorant /app/services/ignorant
RUN pip install --no-cache-dir /app/sdk /app/services/ignorant \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_ignorant:IgnorantService"]
