# Build context is the repo root (see docker-compose.yml) so this can COPY
# the sibling event-contracts package as a local dependency.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY services/event-contracts /app/services/event-contracts
COPY services/failure-lab/requirements.txt /app/services/failure-lab/requirements.txt
RUN pip install --no-cache-dir --upgrade pip==26.1.2 \
    && pip install --no-cache-dir -r /app/services/failure-lab/requirements.txt \
    && pip install --no-cache-dir -e /app/services/event-contracts

COPY services/failure-lab /app/services/failure-lab
WORKDIR /app/services/failure-lab
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
