# TOMOH Weekly Report Automation — Internal Staging Dockerfile (Non-Root)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN groupadd -r tomoh && useradd -r -g tomoh -m tomoh

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY config /app/config
COPY frontend /app/frontend
COPY migrations /app/migrations
COPY scripts /app/scripts

RUN mkdir -p /var/lib/tomoh/uploads /var/lib/tomoh/generated /var/lib/tomoh/templates \
    && chown -R tomoh:tomoh /app /var/lib/tomoh \
    && chmod 700 /var/lib/tomoh/uploads /var/lib/tomoh/generated

USER tomoh
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
