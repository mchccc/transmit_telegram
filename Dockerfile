FROM python:3.7-buster

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./telegram_torrent_bot/telegram_bot.py" ]