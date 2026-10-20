FROM python:3.13-slim

# 容器内必须监听 0.0.0.0，宿主机的端口映射才能把请求转进来；
# 对外只应把端口发布到宿主机回环地址（见 docker-compose.yml），不要直接暴露公网。
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
