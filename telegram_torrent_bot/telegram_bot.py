#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the CC0 license.

import logging
import re
from requests.models import PreparedRequest
from telegram import ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler
from transmission_interface import (add_torrent, get_downloading_torrents,
                                    get_seeding_torrents, get_paused_torrents,
                                    get_torrent, manage_torrent)
from secrets import TELEGRAM_WEBHOOK_ENDPOINT, TELEGRAM_USERID_LIST, TORRENTBOT_TOKEN, TORRENTDAY_KEY


TORRENT_URL_REGEX = r"http[s]?://.+\.torrent"
TORRENTDAY_URL_REGEX = r"http[s]?://(?:www.)torrentday\.com/.+\.torrent"  # (?:[?].+=.+)?
MAGNET_URI_REGEX = r"magnet:\?\S+"

TORRENT_ID_REGEX = r"(\d+)\..*"

DOWNLOADING_FORMATTER = ("{0.id}. {0.name} (added {0.date_added}):\n"
                         "{0.progress:.2f}% - ↓ {1:.3f}MB/s ↑ {2:.3f}MB/s"
                         " - peers: {0.peersConnected} - eta: {3}\n")
SEEDING_FORMATTER = ("{0.id}. {0.name} (added {0.date_added}):\n"
                     "↑ {1:.3f}MB/s - peers: {0.peersConnected} - ratio: {0.ratio}\n")
PAUSED_FORMATTER = ("{0.id}. {0.name} (added {0.date_added}):\n"
                    "{0.progress}% - status: {0.status}\n")

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)

logger = logging.getLogger(__name__)


MAIN, DOWNLOAD, TORRENT, CONFIRM_REMOVAL = range(4)

status_keyboard = [["Downloading", "Seeding", "Paused"]]
status_markup = ReplyKeyboardMarkup(status_keyboard)

download_keyboard = [["Movie", "TV Show", "Other"],
                     ["Cancel"]]
download_markup = ReplyKeyboardMarkup(download_keyboard)

torrent_keyboard = [["Start", "Pause", "Delete"],
                    ["Cancel"]]
torrent_markup = ReplyKeyboardMarkup(torrent_keyboard)

confirm_keyboard = [["Keep data", "Delete data"],
                    ["Cancel"]]
confirm_markup = ReplyKeyboardMarkup(confirm_keyboard)


def prepare_url(url):
    if re.search(TORRENTDAY_URL_REGEX, url):
        params = {"torrent_pass": TORRENTDAY_KEY}
        req = PreparedRequest()
        req.prepare_url(url, params)
        url = req.url

    return url


def data_to_str(user_data):
    facts = list()

    for key, value in user_data.items():
        facts.append("{} - {}".format(key, value))

    return "\n".join(facts).join(["\n", "\n"])


def start(update, context):
    update.message.reply_text(
        "Hi! My name is DownloadMeATorrentBot. I am an interface to a Transmission "
        "torrent client. You can send me a link to a `.torrent` file, or a `magnet` one, "
        "and I will download it; you can also check the status of existing downloads.",
        reply_markup=status_markup)

    return MAIN


def download_torrent(update, context):
    url = prepare_url(context.matches[0].group(0))
    context.user_data["torrent_url"] = url
    update.message.reply_text("Got a torrrent link! What's the nature of its contents?",
                              reply_markup=download_markup)

    return DOWNLOAD


def start_download(update, context):
    category = update.message.text
    context.user_data["category"] = category

    t = add_torrent(context.user_data["torrent_url"], context.user_data["category"])

    update.message.reply_text(f"Neat! Started downloading {t.name}.",
                              reply_markup=status_markup)

    context.user_data.clear()
    return MAIN


def check_torrents(update, context):
    state = context.matches[0].group(0)
    if state == "Downloading":
        torrents = get_downloading_torrents()
        for t in torrents:
            try:
                eta = t.eta
            except ValueError:
                eta = "N/A"
            dr = (t.rateDownload / (1024 * 1024))
            ur = (t.rateUpload / (1024 * 1024))
            update.message.reply_text(DOWNLOADING_FORMATTER.format(t, dr, ur, eta))

    elif state == "Seeding":
        torrents = get_seeding_torrents()
        for t in torrents:
            ur = (t.rateUpload / (1024 * 1024))
            update.message.reply_text(SEEDING_FORMATTER.format(t, ur))

    else:
        torrents = get_paused_torrents()
        for t in torrents:
            update.message.reply_text(PAUSED_FORMATTER.format(t))

    return MAIN


def check_torrent(update, context):
    torrent_id = int(context.matches[0].group(1))
    context.user_data["torrent_id"] = torrent_id
    t = get_torrent(torrent_id)
    update.message.reply_text(f"Selected {t.name}\nWhat would you like to do?",
                              reply_markup=torrent_markup)

    return TORRENT


def handle_download(update, context):
    operation = update.message.text.lower()
    context.user_data["operation"] = operation

    if operation == "delete":
        update.message.reply_text("Delete data too?",
                                  reply_markup=confirm_markup)
        return CONFIRM_REMOVAL
    return perform_operation(update, context)


def perform_operation(update, context):
    remove_data = update.message.text == "Delete data"
    manage_torrent(context.user_data["torrent_id"], context.user_data["operation"], remove_data)

    update.message.reply_text("Done!",
                              reply_markup=status_markup)

    context.user_data.clear()
    return MAIN


def cancel(update, context):
    user_data = context.user_data

    update.message.reply_text("data I had stored:"
                              "{}".format(data_to_str(user_data)),
                              reply_markup=status_markup)

    user_data.clear()
    return MAIN


def main():
    # Create the Updater and pass it your bot"s token.
    updater = Updater(TORRENTBOT_TOKEN, use_context=True)

    updater.start_webhook(listen="0.0.0.0", port=3000, url_path=TORRENTBOT_TOKEN)
    updater.bot.set_webhook(TELEGRAM_WEBHOOK_ENDPOINT + TORRENTBOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Add conversation handler with the states MAIN, DOWNLOAD, and TORRENT
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start, Filters.user(user_id=TELEGRAM_USERID_LIST))],

        states={
            MAIN: [MessageHandler(Filters.regex(TORRENT_URL_REGEX) | Filters.regex(MAGNET_URI_REGEX),
                                  download_torrent),
                   MessageHandler(Filters.regex("^(Downloading|Seeding|Paused)$"),
                                  check_torrents),
                   MessageHandler(Filters.regex(TORRENT_ID_REGEX),
                                  check_torrent),
                   ],
            DOWNLOAD: [MessageHandler(Filters.regex("^(Movie|TV Show|Other)$"),
                                      start_download),
                       ],
            TORRENT: [MessageHandler(Filters.regex("^(Start|Pause|Delete)$"),
                                     handle_download),
                      ],
            CONFIRM_REMOVAL: [
                      MessageHandler(Filters.regex("^(Keep data|Delete data)$"),
                                     perform_operation),
                      ],
        },

        fallbacks=[MessageHandler(Filters.regex("^Cancel$"), cancel)]
    )

    dp.add_handler(conv_handler)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == "__main__":
    main()
