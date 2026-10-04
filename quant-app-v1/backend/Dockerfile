# Multi-stage build for FastAPI backend
# Stage 1: Builder
FROM python:3.12-slim as builder

WORKDIR /tmp

# Install build dependencies (git: TradingAgents is fetched from GitHub)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip setuptools wheel

# Copy requirements and create wheels (explicit packaging for slowapi/limits)
COPY requirements.txt .
RUN pip install --user --no-cache-dir --upgrade pip && \
    pip install --user --no-cache-dir -r requirements.txt && \
    pip install --user --no-cache-dir 'packaging>=20.0' 'passlib>=1.7'

# Tauric Research TradingAgents (multi-agent LLM trading framework) — the
# agentic features of the app. Installed separately because its dependency
# floor (pandas>=3) differs from requirements.txt; pip upgrades pandas here.
RUN pip install --user --no-cache-dir 'tradingagents @ git+https://github.com/TauricResearch/TradingAgents.git'

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    python3-packaging \
    python3-passlib \
    && rm -rf /var/lib/apt/lists/*

# Ensure Python can find system site-packages (packaging for slowapi)
ENV PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}"

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY quant-app-v1/backend/app ./app

# Set environment
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

# Expose port
EXPOSE 8000

# Run app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
