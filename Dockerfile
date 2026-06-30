# Dockerfile for narrascape
# Provides a complete environment with FFmpeg, Python, and all dependencies

FROM python:3.12-slim

LABEL maintainer="narrascape"
LABEL description="Narrascape video pipeline container"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ffprobe \
    fonts-noto-cjk \
    fonts-dejavu \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

# Install Python dependencies, including the optional Streamlit dashboard.
RUN pip install --no-cache-dir -e ".[dev,dashboard]"

# Create directories for project assets
RUN mkdir -p /app/projects /app/output

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV NARRASCAPE_FFMPEG=/usr/bin/ffmpeg

# Default entrypoint
ENTRYPOINT ["narrascape"]
CMD ["--help"]
