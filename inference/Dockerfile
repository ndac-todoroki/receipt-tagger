# ビルドコンテキストはリポジトリのルート（docker-compose.yml から指定）

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 骨組みの段階では軽量イメージにする。GPUでモデルを動かす段でCUDA対応イメージへ替える
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY inference/pyproject.toml inference/uv.lock inference/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY inference/src ./src
RUN uv sync --frozen --no-dev
COPY --from=frontend /frontend/dist /app/static
ENV STATIC_DIR=/app/static PATH=/opt/venv/bin:$PATH
EXPOSE 8000
CMD ["uvicorn", "receipt_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
