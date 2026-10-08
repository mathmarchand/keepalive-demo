# ---------------------------------------------------------------------------
# Stage 1: build the static web assets (Vanilla CSS, Ubuntu fonts, logo)
#
# The dashboard used to load these from assets.ubuntu.com at runtime, which
# often fails. They are now built and downloaded once here and served by Flask
# from /static/vendor/. Docker caches this stage, so it only runs again when
# something in assets/ changes.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS assets

RUN apk add --no-cache curl

WORKDIR /build

# Compile Vanilla from npm (with $assets-path pointed at /static/vendor/)
RUN npm init -y >/dev/null && \
    npm install --no-audit --no-fund vanilla-framework@3.0.0 sass@1.105.1

COPY assets/vanilla.scss .
RUN mkdir -p /out/static/vendor && \
    npx sass --no-source-map --style=compressed --quiet --load-path=node_modules \
        vanilla.scss /out/static/vendor/vanilla.min.css

# Download the fonts referenced by the CSS plus the Canonical logo.
# assets.ubuntu.com is unreliable: the script retries each file and the build
# fails if anything is still missing. Just re-run the build if that happens.
# Override with --build-arg ASSETS_BASE_URL=<mirror> to use a mirror.
ARG ASSETS_BASE_URL=https://assets.ubuntu.com/v1
COPY assets/fetch-assets.sh .
RUN ASSETS_BASE_URL="$ASSETS_BASE_URL" sh fetch-assets.sh /out/static/vendor/vanilla.min.css /out/static/vendor

# ---------------------------------------------------------------------------
# Stage 2: application image
# ---------------------------------------------------------------------------
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python along with C build tools and Python development headers
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Set up virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade core build utilities and install requirements
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY --from=assets /out/static ./static
EXPOSE 8080

CMD ["python3", "app.py"]
