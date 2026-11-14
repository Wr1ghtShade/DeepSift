# Build from the repository root:
#   docker build -f services/whatsapp/Dockerfile -t deepsift/svc-whatsapp .
# Link the dedicated account once, then start the worker:
#   docker compose --profile whatsapp run --rm svc-whatsapp link --phone +33…
#   docker compose --profile whatsapp up -d svc-whatsapp
FROM node:22-slim

ENV NODE_ENV=production DEEPSIFT_DATA_DIR=/data
WORKDIR /app

COPY services/whatsapp/package.json services/whatsapp/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY services/whatsapp/manifest.yaml ./
COPY services/whatsapp/src ./src

RUN mkdir -p /data && chown node /data
USER node
VOLUME ["/data"]
ENTRYPOINT ["node", "src/cli.js"]
CMD ["worker"]
