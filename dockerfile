FROM python:3.9-slim

WORKDIR /app

# Sistem bağımlılıklarını yükle
RUN apt-get update && apt-get install -y \
    wget unzip libglib2.0-0 libnss3 libfontconfig1 libxrender1 libxi6 libxtst6 libxss1 \
    libappindicator3-1 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 fonts-liberation xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Chromium yükle (en son sürüm)
RUN apt-get update && apt-get install -y chromium \
    && rm -rf /var/lib/apt/lists/*

# ChromeDriver'ı yükle (Chromium sürümüne uygun)
RUN CHROMIUM_VERSION=$(chromium --version | awk '{print $2}') \
    && wget -O /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/$CHROMIUM_VERSION/linux64/chromedriver-linux64.zip" \
    && unzip /tmp/chromedriver.zip -d /usr/local/bin/ \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver.zip /usr/local/bin/chromedriver-linux64

# Python bağımlılıklarını yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY . .

# Flask portunu aç
EXPOSE 10000

# Uygulamayı çalıştır
CMD ["python", "app.py"]