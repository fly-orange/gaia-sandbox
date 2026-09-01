FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash coreutils curl ca-certificates ffmpeg poppler-utils tesseract-ocr \
    unzip git procps tmux chromium nodejs npm && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /usr/local/bin/
WORKDIR /opt/gaia
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY vendor ./vendor
RUN uv sync --locked --extra sandbox --no-dev \
    && uv venv /opt/fetch \
    && uv pip install --python /opt/fetch/bin/python mcp-server-fetch==2025.4.7 \
    && npm install --prefix /opt/tavily tavily-mcp@0.2.1 \
    && test -x /opt/tavily/node_modules/.bin/tavily-mcp

RUN useradd --create-home --uid 1000 agent \
    && mkdir /workspace \
    && chown -R agent:agent /workspace /opt/gaia /opt/browsers
USER 1000:1000
ENV HOME=/home/agent PATH=/opt/gaia/.venv/bin:/opt/fetch/bin:$PATH
WORKDIR /workspace
CMD ["sleep", "infinity"]
