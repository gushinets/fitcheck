FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    FITCHECK_ENV=production \
    FITCHECK_HOST=0.0.0.0 \
    FITCHECK_PORT=8000
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
    && groupadd --gid 10001 fitcheck \
    && useradd --uid 10001 --gid fitcheck --no-create-home fitcheck
USER fitcheck
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]
CMD ["/app/.venv/bin/python", "-m", "fitcheck_backend"]
