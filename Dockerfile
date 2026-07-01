# Use Python 3.11 slim image for a smaller footprint
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

# Set working directory
WORKDIR /app

# Install system dependencies
# ffmpeg: for video/audio processing
# libsm6, libxext6: for OpenCV
# libgomp1: for ONNX Runtime (required for ARM64/t4g instances)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend /app/backend
COPY frontend /app/frontend

# Create uploads directory and ensure it exists
RUN mkdir -p /app/backend/uploads

# Set working directory to backend for runtime
WORKDIR /app/backend

# Expose port (default for API)
EXPOSE 6969

# The default command is for the API
# Docker Compose will override this for the worker
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6969"]
