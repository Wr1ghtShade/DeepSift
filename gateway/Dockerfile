# Build from the repository root:
#   docker build -f gateway/Dockerfile -t deepsift/gateway .

# 1. The web GUI
FROM node:22-alpine AS gui
WORKDIR /gui
COPY gui/package.json gui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY gui/ ./
RUN npm run build

# 2. The gateway, serving the GUI
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DEEPSIFT_HOST=0.0.0.0 DEEPSIFT_PORT=8000 DEEPSIFT_DATA_DIR=/data \
    DEEPSIFT_GUI_DIR=/app/gui
WORKDIR /app

COPY sdk /app/sdk
COPY gateway /app/gateway
RUN pip install --no-cache-dir /app/sdk /app/gateway \
    && useradd --system --no-create-home deepsift \
    && mkdir -p /data/blobs && chown -R deepsift /data
COPY --from=gui /gui/dist /app/gui

USER deepsift
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]
CMD ["deepsift-gateway"]
