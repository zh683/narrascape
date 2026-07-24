FROM python:3.13-slim AS wheel-builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels ".[dashboard,workbench]"


FROM python:3.13-slim AS runtime

LABEL maintainer="narrascape"
LABEL description="Narrascape AI film-production pipeline"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    fonts-dejavu \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=wheel-builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        "narrascape[dashboard,workbench]" \
    && rm -rf /wheels \
    && ffmpeg -version \
    && ffprobe -version \
    && narrascape --help

WORKDIR /app
RUN useradd --create-home --uid 10001 narrascape \
    && mkdir -p /app/projects /app/output \
    && chown -R narrascape:narrascape /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NARRASCAPE_FFMPEG=/usr/bin/ffmpeg \
    NARRASCAPE_FFPROBE=/usr/bin/ffprobe

USER narrascape
ENTRYPOINT ["narrascape"]
CMD ["--help"]


FROM runtime AS development

USER root
COPY . /app
RUN python -m pip install --no-cache-dir -e ".[dev,dashboard,workbench]"
USER narrascape
ENTRYPOINT []
CMD ["pytest", "-q", "--tb=short", "--no-cov"]


FROM runtime AS production
