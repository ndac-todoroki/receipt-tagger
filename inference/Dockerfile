# ビルドコンテキストはリポジトリのルート（docker-compose.yml から指定）

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 推論はCPUで動かす（OCRは ONNX Runtime、埋め込みは CPU 版 torch）
FROM python:3.12-slim AS app
# RapidOCR が使う OpenCV の実行に必要
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0     && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY inference/pyproject.toml inference/uv.lock inference/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY inference/src ./src
RUN uv sync --frozen --no-dev
COPY --from=frontend /frontend/dist /app/static
COPY config /app/config
# モデルの重みはイメージに焼かず、/models のボリュームに初回起動時にダウンロードする
ENV STATIC_DIR=/app/static CONFIG_DIR=/app/config MODEL_DIR=/models HF_HOME=/models/hf     PATH=/opt/venv/bin:$PATH
EXPOSE 8000
CMD ["uvicorn", "receipt_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
