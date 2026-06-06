# ── Base ────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

WORKDIR /app

# System dependencies (layer cached until this list changes)
RUN apt-get update && apt-get install -y --no-install-recommends \
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

# ── Dependencies ─────────────────────────────────────────────────────────────
# Copy requirements first so pip layer is cached unless requirements change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application ──────────────────────────────────────────────────────────────
COPY . .

# Embed the git commit SHA as a build arg so you can verify which
# code is running inside the container: GET /health returns it.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

# Runtime directories (also created via volume mounts, but needed for non-volume runs)
RUN mkdir -p generated_pdfs logs

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "webhook.py"]