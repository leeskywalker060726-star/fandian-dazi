FROM node:24-alpine AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY apps/web ./apps/web
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY apps ./apps
COPY scripts/init_db.py ./scripts/init_db.py
COPY --from=web /app/dist ./dist
RUN useradd --create-home app && mkdir -p /app/.runtime && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
