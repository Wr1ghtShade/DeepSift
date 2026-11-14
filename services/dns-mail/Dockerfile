# Build from the repository root:
#   docker build -f services/dns-mail/Dockerfile -t deepsift/svc-dns-mail .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY sdk /app/sdk
COPY services/dns-mail /app/services/dns-mail
RUN pip install --no-cache-dir /app/sdk /app/services/dns-mail \
    && useradd --system --no-create-home deepsift

USER deepsift
CMD ["python", "-m", "deepsift_sdk.worker", "deepsift_svc_dns_mail:DnsMailService"]
