FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8765

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY radar ./radar
COPY assets ./assets
COPY README.md LICENSE .env.example ./

VOLUME ["/app/data"]
EXPOSE 8765

CMD ["python", "-m", "radar.web"]
