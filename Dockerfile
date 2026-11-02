FROM ghcr.io/astral-sh/uv:0.11.33 AS uv
FROM python:3.13-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY config.py models.py pdf_utils.py validators.py llm_service.py workflow.py ./
COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --uid 10001 --create-home paperlens && mkdir -p /data/documents && chown -R paperlens:paperlens /data
ENV PATH="/app/.venv/bin:$PATH" STORAGE_ROOT=/data/documents
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
USER paperlens
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3)"
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
