FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT \
    --workers 1 \
    --timeout 120 \
    --graceful-timeout 150 \
    --keep-alive 5 \
    app:app"]