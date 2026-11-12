FROM alpine:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apk add --no-cache \
      python3 \
      libpq \
      py3-fastapi \
      uvicorn \
      py3-httpx \
      py3-pydantic \
      py3-psycopg \
      py3-pika \
      py3-jsonschema && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    adduser -D -u 10001 sre_sim

COPY requirements.txt /app/requirements.txt
COPY services /app/services
COPY traffic /app/traffic
COPY observability /app/observability

USER sre_sim
EXPOSE 8000

CMD ["uvicorn", "services.api_gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
