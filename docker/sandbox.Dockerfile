FROM python:3.12-slim-bookworm
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash coreutils curl ca-certificates ffmpeg poppler-utils tesseract-ocr \
    unzip git procps && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests beautifulsoup4 pandas openpyxl \
    pillow pypdf python-docx python-pptx playwright \
    && playwright install --with-deps chromium
RUN useradd --create-home --uid 1000 agent && mkdir /workspace \
    && chown agent:agent /workspace
USER 1000:1000
ENV HOME=/home/agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
