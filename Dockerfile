# syntax=docker/dockerfile:1.7
# static-ffmpeg 9.0.2 and alpine 3.24, pinned by multi-arch index digest.
FROM mwader/static-ffmpeg@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b AS ffmpeg
FROM alpine@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6 AS base

FROM base AS builder
RUN apk add --no-cache python3
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY requirements.txt .
# The lock holds hashes, so a swapped package fails the build. --seed keeps pip in the venv for the yt-dlp upgrade at boot.
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv venv --seed --python /usr/bin/python3 /venv && \
    uv pip install --python /venv/bin/python --require-hashes -r requirements.txt

# Keep this the last stage: it is the only one that gets published. Bare alpine plus python3, so no pip, apk or
# toolchain beyond what the venv needs; the venv's python symlink targets /usr/bin/python3, which is the same here.
FROM base AS runner
RUN apk add --no-cache python3 libstdc++ \
    && adduser -D -u 1000 appuser \
    && mkdir -p /app/cache \
    && chown appuser:appuser /app /app/cache
WORKDIR /app
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=builder --chown=appuser:appuser /venv /venv
COPY --chown=appuser:appuser templates ./templates
COPY --chown=appuser:appuser proxies.txt app-web.py utils.py ./
COPY --chown=appuser:appuser --chmod=755 entrypoint.sh ./
ENV PATH=/venv/bin:$PATH \
    PORT=3000 \
    PYTHONUNBUFFERED=1
USER appuser
EXPOSE 3000
# Liveness only; busybox nc starts no Python process per probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["nc", "-z", "127.0.0.1", "3000"]
CMD ["/app/entrypoint.sh"]
