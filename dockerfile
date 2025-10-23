FROM python:3.9-slim

WORKDIR /app

# Sistem bağımlılıklarını yükle
RUN apt-get update && apt-get install -y \
    wget unzip libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 libxrender1 libxi6 libxtst6 libxss1 \
    libappindicator3-1 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 fonts-liberation xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Chromium yükle (141 sürümünü sabitlemek için)
RUN apt-get update && apt-get install -y chromium=141.0.7390.107-1~deb12u1 \
    && rm -rf /var/lib/apt/lists/*

# ChromeDriver 141 sürümünü yükle
RUN wget -O /tmp/chromedriver.zip https://storage.googleapis.com/chrome-for-testing-public/141.0.7390.107/linux64/chromedriver-linux64.zip \
    && unzip /tmp/chromedriver.zip -d /usr/local/bin/ \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver.zip /usr/local/bin/chromedriver-linux64

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "app.py"]