# One image: builds the web app, then serves it and the API from FastAPI.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIST=/app/web/dist
WORKDIR /app/api
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ ./
COPY --from=web /web/dist /app/web/dist
# Migrations run on every start; they are forward-only and safe to repeat.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
