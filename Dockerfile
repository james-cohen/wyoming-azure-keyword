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

# Expose Wyoming default port
EXPOSE 10400

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the Wyoming server
ENTRYPOINT ["python", "-m", "wyoming_azure_keyword"]

# Default command arguments (can be overridden)
CMD ["--uri", "tcp://0.0.0.0:10400", "--model-path", "/models/keyword.table", "--keyword-name", "azure_wake_word"]

