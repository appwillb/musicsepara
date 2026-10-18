FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system audio dependencies and typography fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    fonts-dejavu-core \
    fonts-liberation \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch & Demucs & FastAPI & Uvicorn & dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    python-multipart \
    websockets \
    soundfile \
    scipy \
    lameenc \
    httpx \
    beautifulsoup4 \
    pillow \
    demucs

# Copy application files (excluding items in .dockerignore)
COPY . /app

# Ensure runtime directories exist with appropriate permissions
RUN mkdir -p /app/uploads /app/outputs /app/data/stageprompter

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
