FROM python:3.11-slim

# 1. Use a neutral workspace folder name
WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 2. This copies your local 'app' folder into '/workspace/app'
COPY ./app ./app

COPY .env.docker . 

# 3. Point Uvicorn back to app.main:app
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]