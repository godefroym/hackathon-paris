FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY workflows/requirements.worker.txt /tmp/requirements.worker.txt
RUN pip install --no-cache-dir -r /tmp/requirements.worker.txt

