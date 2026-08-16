FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY web ./web
COPY config.example.json ./config.example.json

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api:app --host 0.0.0.0 --port ${PORT}"]
