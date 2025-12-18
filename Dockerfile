# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Create a directory for models
RUN mkdir -p /models

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MODEL_PATH=/models/keyword.table
ENV KEYWORD_NAME=azure_wake_word
ENV DEBUG=false
ENV PORT=10400

# Expose Wyoming port
EXPOSE ${PORT}

# Run the Wyoming server
ENTRYPOINT ["python", "-m", "wyoming_azure_keyword"]


