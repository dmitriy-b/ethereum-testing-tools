FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Clone ethstaker-deposit-cli repository
RUN git clone https://github.com/dmitriy-b/ethstaker-deposit-cli /app/ethstaker-deposit-cli

# Copy requirements.txt and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install requirements from ethstaker-deposit-cli
RUN pip install --no-cache-dir -r /app/ethstaker-deposit-cli/requirements.txt

# Add ethstaker repository to Python path
RUN ln -s /app/ethstaker-deposit-cli/ethstaker_deposit /app/ethstaker_deposit

# Copy the scripts directory
COPY scripts/ /app/scripts/

# Set Python as the entrypoint
ENTRYPOINT ["python3"] 