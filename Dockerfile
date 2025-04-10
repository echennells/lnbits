FROM python:3.10-slim-bookworm

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        curl \
        pkg-config \
        build-essential \
        libnss-myhostname \
        nodejs \
        npm && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.3
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Setup Poetry environment variables
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

# Copy pyproject.toml and poetry.lock first for better caching
COPY pyproject.toml poetry.lock ./
COPY package.json* package-lock.json* ./

# Create data directory
RUN mkdir -p data

# Install dependencies
RUN poetry install --no-root --only main

# Copy the rest of the application
COPY . .

# Install the package in development mode
RUN poetry install --only main

# Install additional Python packages required by taproot_assets
RUN poetry run pip install "grpcio==1.65.5" "grpcio-tools==1.65.5" "httpx>=0.25.0" "loguru>=0.7.0" "websockets" "lnd-grpc"

# Install Node.js dependencies if package.json exists
RUN if [ -f package.json ]; then npm install && npm install vue-qrcode-component; fi

# Environment variables
ENV LNBITS_PORT="5000" \
    LNBITS_HOST="0.0.0.0" \
    PYTHONPATH="${PYTHONPATH}:/app" \
    PATH="/app/.venv/bin:$PATH"

# Expose port
EXPOSE 5000

# Start LNbits
CMD ["sh", "-c", "cd /app && poetry run lnbits --port $LNBITS_PORT --host $LNBITS_HOST"]
