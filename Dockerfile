FROM python:3.7-buster

RUN apt-get update && apt-get install chromium chromium-driver rustc -y

WORKDIR /usr/src/app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD [ "python", "./telegram_torrent_bot/telegram_bot.py" ]
