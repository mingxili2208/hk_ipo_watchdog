FROM python:3.12-slim

WORKDIR /app

# Playwright/Chromium 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium 浏览器（不重复安装系统依赖，已手动安装）
RUN playwright install chromium

COPY . .

RUN mkdir -p data/raw data/pdf data/exports logs

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Hong_Kong

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["run"]
