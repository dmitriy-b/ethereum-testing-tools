FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and curl for uv installer
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (https://github.com/astral-sh/uv)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Clone ethstaker-deposit-cli repository
RUN git clone https://github.com/dmitriy-b/ethstaker-deposit-cli /app/ethstaker-deposit-cli

# Copy dependency manifests and install with uv
COPY requirements.txt pyproject.toml ./
RUN uv pip install --system -r requirements.txt
RUN uv pip install --system -r /app/ethstaker-deposit-cli/requirements.txt

# Add ethstaker repository to Python path
RUN ln -s /app/ethstaker-deposit-cli/ethstaker_deposit /app/ethstaker_deposit

# Copy the scripts directory
COPY scripts/ /app/scripts/

# Set Python as the entrypoint (uv is available for runners)
ENTRYPOINT ["python3"]
