# Resmi Playwright Python imajı (Chromium + tüm bağımlılıklar hazır)
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

WORKDIR /app

# Gereksinimleri kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tüm kodunu kopyala
COPY . .

# Render'ın beklediği PORT değişkenini kullan
EXPOSE $PORT

# Production için gunicorn ile çalıştır (Flask app'in adı app.py ise)
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "app:app"]