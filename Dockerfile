FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/raw data/pdf data/exports logs

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Hong_Kong

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["run"]
