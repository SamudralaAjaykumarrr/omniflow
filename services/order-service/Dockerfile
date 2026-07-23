# Build context is the repo root (see docker-compose.yml) so this can COPY
# the sibling event-contracts package as a local dependency.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY services/event-contracts /app/services/event-contracts
COPY services/order-service/requirements.txt /app/services/order-service/requirements.txt
RUN pip install --no-cache-dir -r /app/services/order-service/requirements.txt \
    && pip install --no-cache-dir -e /app/services/event-contracts

COPY services/order-service /app/services/order-service
WORKDIR /app/services/order-service
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
