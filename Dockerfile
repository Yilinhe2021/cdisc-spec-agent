# ---- frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---- backend
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SPECFORGE_DATA_DIR=/data
WORKDIR /app
COPY backend/ backend/
RUN pip install --no-cache-dir "./backend[anthropic,openai]"
COPY examples/ examples/
RUN python examples/make_examples.py
COPY --from=web /web/dist frontend/dist
RUN useradd -m specforge && mkdir -p /data && chown specforge /data
USER specforge
EXPOSE 8000
CMD ["uvicorn", "specforge.api.app:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
