# Gateway API image.
#
# Build with THIS directory as the context so every COPY path below resolves:
#     docker build -t gateway-api quant-app-v1/backend
#     docker run --rm -p 8000:8000 --env-file ../../.env gateway-api
#
# models/ and vendor/ are excluded by .dockerignore: they are 441 MB of local
# ML assets that v1 does not ship (docs/SRS.md §8), and including them is what
# pushed earlier cloud builds past their limits.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# requirements.txt is the trimmed app-runtime set. requirements-full.txt is the
# CI/local superset and is deliberately not used here.
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN useradd -m -u 1000 appuser

WORKDIR /app

# Application code, plus the instrument catalogue that /catalogue and
# /stocks/search read at run time.
COPY app ./app
COPY data ./data

# Writable state lives under GATEWAY_DATA_DIR, never beside the modules.
RUN mkdir -p /app/runtime && chown -R appuser:appuser /app
ENV GATEWAY_DATA_DIR=/app/runtime

USER appuser

EXPOSE 8000

# Uses the stdlib: slim images carry neither curl nor httpx guarantees.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
