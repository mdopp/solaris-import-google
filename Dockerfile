FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8097

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8097

# Runs as root so that, under rootless podman, writes into the shared
# host trees (radicale collections, notes vault) land as host uid 1000 —
# the owner Radicale/Syncthing expect.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
