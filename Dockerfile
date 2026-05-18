FROM mwader/static-ffmpeg:6.1.1 AS ffmpeg

FROM python:3.13-slim

WORKDIR /app

COPY --from=ffmpeg /ffmpeg /usr/local/bin/
COPY --from=ffmpeg /ffprobe /usr/local/bin/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh \
 && useradd -u 1000 -m appuser \
 && mkdir -p /app/cache \
 && chown -R appuser:appuser /app

USER appuser

ENV PORT=3000
EXPOSE 3000

CMD ["/app/entrypoint.sh"]
