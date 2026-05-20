# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install ONLY essential dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libgobject-2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p generated_pdfs logs

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "webhook.py"]