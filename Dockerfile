FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Invariant 12: Single worker with threads ensures in-memory pending proposal codes
# are preserved across requests within the container instance.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request, os; port = os.getenv('PORT', '8080'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

CMD exec gunicorn --workers 1 --threads 8 --timeout 0 --bind 0.0.0.0:$PORT api_server:app
