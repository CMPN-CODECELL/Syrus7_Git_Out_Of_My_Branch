# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for AlphaStreams

# Stage 1: Build dependencies and wheels
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# Stage 2: Lean runtime
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US.UTF-8

# Install runtime system deps for PostgreSQL/TimescaleDB & Redis & Supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg lsb-release supervisor redis-server tzdata locales \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && locale-gen en_US.UTF-8 \
    && echo "deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && wget --quiet -O /etc/apt/trusted.gpg.d/pgdg.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb https://packagecloud.io/timescale/timescaledb/debian/ bookworm main" > /etc/apt/sources.list.d/timescaledb.list \
    && wget --quiet -O /etc/apt/trusted.gpg.d/timescaledb.asc https://packagecloud.io/timescale/timescaledb/gpgkey \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-15 postgresql-client-15 timescaledb-2-postgresql-15 \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built python wheels from builder
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application source & configs
COPY . .
COPY docker/supervisord.conf /supervisord.conf
COPY docker/start.sh /start.sh
RUN chmod +x /start.sh

# Expose ports
EXPOSE 8000

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start supervisor via entrypoint wrapper script
CMD ["/start.sh"]
