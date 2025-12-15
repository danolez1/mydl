FROM mwader/static-ffmpeg:6.1.1 AS ffmpeg

FROM python:3.13-slim

WORKDIR /app

# Copy ffmpeg binaries
COPY --from=ffmpeg /ffmpeg /usr/local/bin/
COPY --from=ffmpeg /ffprobe /usr/local/bin/

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the application port
EXPOSE 3000

# Run the application
# Using 'fastapi run' which is production-ready (requires fastapi[standard])
CMD ["fastapi", "run", "app-web.py", "--port", "3000"]
