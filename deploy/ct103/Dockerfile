FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PADEL_AVAILABILITY_DB=/data/catalog.sqlite3 \
    PADEL_AVAILABILITY_DATA=/app/data \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY data ./data

RUN python -m pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev --group browser --group web \
    && rm -rf /root/.cache/uv

EXPOSE 8082

CMD ["padel-availability-web"]
