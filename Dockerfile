# Build stage
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies and uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN pip install --no-cache-dir .

# Copy project and install
COPY . .
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.13-slim

WORKDIR /app

# Install only runtime dependencies (libasound2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Create models directory
RUN mkdir -p /models

EXPOSE 10400
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "wyoming_azure_keyword"]
CMD ["--uri", "tcp://0.0.0.0:10400", "--model-path", "/models/keyword.table", "--keyword-name", "azure_wake_word"]