FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERIFYNET_HOST=0.0.0.0 \
    PORT=8765

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /app/data /app/reports
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS -o /dev/null -H "X-VerifyNet-Access: ${VERIFYNET_ACCESS_TOKEN}" http://127.0.0.1:8765/api/status

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8765"]
