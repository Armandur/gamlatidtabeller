FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# WeasyPrint behover pango/harfbuzz; DejaVu ar lapparnas typsnitt
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DATA_DIR=/data \
    PORT=8000 \
    ADMIN_PORT=8001

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ app/

# -m ger hemkatalog sa att fontconfig far en skrivbar cache
RUN useradd -r -m -u 1000 appuser && mkdir /data && chown appuser /data
USER appuser
ENV HOME=/home/appuser

VOLUME /data
EXPOSE 8000 8001

CMD ["python", "-m", "app.run"]
