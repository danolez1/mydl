#!/bin/sh
set -e

echo "[entrypoint] yt-dlp version: $(yt-dlp --version 2>/dev/null || echo unknown)"

# Background upgrade into the venv, picked up on next restart. Don't block server start.
# set -e is disabled inside the subshell so a failed upgrade never kills boot.
(
    if pip install --no-cache-dir --quiet --upgrade --pre yt-dlp >/tmp/ytdlp-update.log 2>&1; then
        echo "[entrypoint] yt-dlp upgrade staged for next restart: $(yt-dlp --version 2>/dev/null || echo unknown)"
    else
        echo "[entrypoint] yt-dlp upgrade FAILED"
        tail -10 /tmp/ytdlp-update.log || true
    fi
) &

exec fastapi run app-web.py --port "${PORT:-3000}"
