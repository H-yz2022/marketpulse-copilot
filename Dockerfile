# ---- Stage 1: build the React frontend -------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python API that also serves the built frontend ---------------
FROM python:3.11-slim
WORKDIR /app
# MALLOC_ARENA_MAX: glibc otherwise keeps a malloc arena per thread, which
# inflates RSS in a threaded server and pushes a 512 MB instance over its limit.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MALLOC_ARENA_MAX=2

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt
# Bake the embedding model into the image so the first semantic query doesn't download it.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2 as E; E()._download_model_if_not_exists()"

COPY pyproject.toml README.md ./
COPY src/ src/
COPY scripts/ scripts/
COPY seed/ seed/
RUN pip install --no-deps -e .
COPY --from=web /web/dist frontend/dist

# Render/Railway/Cloud Run inject $PORT; default to 8000 locally.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn marketpulse.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
