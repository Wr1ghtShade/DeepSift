# Build from the repository root:
#   docker build -f services/gravatar/Dockerfile -t deepsift/svc-gravatar .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/gravatar /app/services/gravatar
RUN pip install --no-cache-dir /app/sdk /app/services/gravatar \
    && groupadd --system --gid 10001 deepsift \
    && useradd --system --no-create-home --uid 10001 --gid 10001 deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_gravatar:GravatarService"]
