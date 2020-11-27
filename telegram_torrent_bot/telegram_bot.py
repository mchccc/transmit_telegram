#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the CC0 license.

import logging
import re
import json
import html
from selenium.webdriver import Chrome
from selenium.webdriver import ChromeOptions as Options
from requests.models import PreparedRequest
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackQueryHandler
from transmission_interface import (add_torrent, get_downloading_torrents,
                                    get_seeding_torrents, get_paused_torrents,
                                    get_torrent, manage_torrent)
from secrets import TELEGRAM_WEBHOOK_ENDPOINT, TELEGRAM_USERID_LIST, TORRENTBOT_TOKEN, TORRENTDAY_KEY


TORRENT_URL_REGEX = r"http[s]?://.+\.torrent"
TORRENTDAY_URL_REGEX = r"http[s]?://(?:www.)torrentday\.com/.+\.torrent"  # (?:[?].+=.+)?
MAGNET_URI_REGEX = r"(magnet:\?[^\"\s]+)"
URL_REGEX = r"http[s]?://[^\"\s]+"

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
                    level=logging.INFO, filename="telegram_bot.log", filemode="w")
logger = logging.getLogger(__name__)


# select torrent from webpage
PICK_NEW_TORRENT = "pick_torrent"
PICK_NEW_TORRENT_DATA = {"a": PICK_NEW_TORRENT}
PICK_NEW_TORRENT_INLINE_KEYBOARD = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="add",
                                      callback_data=json.dumps(PICK_NEW_TORRENT_DATA))]
            ])

# select torrent type
ADD_NEW_TORRENT = "add_torrent"
SELECT_MOVIE_DATA = {"a": ADD_NEW_TORRENT,
                     "t_type": "movie"}
SELECT_TVSHOW_DATA = {"a": ADD_NEW_TORRENT,
                      "t_type": "tv show"}
SELECT_OTHER_DATA = {"a": ADD_NEW_TORRENT,
                     "t_type": "other"}
SELECT_TORRENT_TYPE_INLINE_KEYBOARD = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="🎥",
                                      callback_data=json.dumps(SELECT_MOVIE_DATA)),
                 InlineKeyboardButton(text="📺",
                                      callback_data=json.dumps(SELECT_TVSHOW_DATA)),
                 InlineKeyboardButton(text="🌚",
                                      callback_data=json.dumps(SELECT_OTHER_DATA))]
            ])

# manage added torrent
MANAGE_TORRENT = "manage_torrent"

# bot states
MAIN, PICK_TORRENT, DOWNLOAD, TORRENT_STATUS, CONFIRM_REMOVAL = range(5)

status_keyboard = [["Downloading", "Seeding", "Paused"]]
status_markup = ReplyKeyboardMarkup(status_keyboard)

cancel_keyboard = [["Cancel"]]
cancel_markup = ReplyKeyboardMarkup(cancel_keyboard)


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


def fetch_page_html(url):
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--headless')
    options.add_argument('--disable-dev-shm-usage')
    options.binary_location = "/usr/bin/chromium"
    browser = Chrome(executable_path="/usr/bin/chromedriver", options=options)
    browser.get(url)
    html = browser.page_source
    browser.close()
    return html


def start(update, context):
    update.message.reply_text(
        "Hi! My name is DownloadMeATorrentBot. I am an interface to a Transmission "
        "torrent client. You can send me a link to a `.torrent` file (or a `magnet` one) "
        "or one to a webpage linking to one, and I will download it; "
        "you can also check the status of existing downloads.",
        reply_markup=status_markup)

    return MAIN


def handle_torrent_magnet_link(update, context):
    message = update.message.reply_text(f"Looking for valid links")

    url = context.matches[0].group(0)

    return pick_new_download(message, url)


def get_links_from_webpage(update, context):
    message = update.message.reply_text(f"Looking for valid links")

    url = context.matches[0].group(0)
    html = fetch_page_html(url)
    logger.info("got page")

    return pick_new_download(message, html)


def pick_new_download(message, text):
    torrent_urls = set([m.group() for m in re.finditer(TORRENT_URL_REGEX, text, re.MULTILINE)])
    logger.info(torrent_urls)
    if torrent_urls:
        message.edit_text("Found these torrent files:")
        for index, url in enumerate(torrent_urls, start=1):
            message.reply_text(f"{index}. {url}", reply_markup=PICK_NEW_TORRENT_INLINE_KEYBOARD)

    magnet_urls = set([m.group() for m in re.finditer(MAGNET_URI_REGEX, text, re.MULTILINE)])
    logger.info(magnet_urls)
    if magnet_urls:
        message.edit_text("Found these magnet URLs:")
        for index, url in enumerate(magnet_urls, start=len(torrent_urls) + 1):
            message.reply_text(f"{index}. {url}", reply_markup=PICK_NEW_TORRENT_INLINE_KEYBOARD)

    if torrent_urls or magnet_urls:
        message.edit_text("I found these links, which ones would you like to add?")
    else:
        message.edit_text("I couldn't find any torrent or magnet links at that address.")

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
            update.message.reply_text(
                DOWNLOADING_FORMATTER.format(t, dr, ur, eta),
                reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(text="pause download",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "pause",
                                                                "t_id": t.id})),
                         InlineKeyboardButton(text="remove",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete",
                                                                "t_id": t.id}))]
                ])
            )

    elif state == "Seeding":
        torrents = get_seeding_torrents()
        for t in torrents:
            ur = (t.rateUpload / (1024 * 1024))
            update.message.reply_text(
                SEEDING_FORMATTER.format(t, ur),
                reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(text="pause torrent",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "pause",
                                                                "t_id": t.id})),
                         InlineKeyboardButton(text="remove",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete",
                                                                "t_id": t.id}))]
                ])
            )

    else:
        torrents = get_paused_torrents()
        for t in torrents:
            update.message.reply_text(
                PAUSED_FORMATTER.format(t),
                reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(text="start download",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "start",
                                                                "t_id": t.id})),
                         InlineKeyboardButton(text="remove",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete",
                                                                "t_id": t.id}))]
                ])
            )

    return MAIN


def cancel(update, context):
    user_data = context.user_data

    update.message.reply_text("data I had stored:"
                              "{}".format(data_to_str(user_data)),
                              reply_markup=status_markup)

    user_data.clear()
    return MAIN


def handle_callback(update, context):
    # logger.info(f"callback {update['callback_query']['message']['text']}\n{update['callback_query']['data']}")
    data = json.loads(update["callback_query"]["data"])
    logger.info(f"callback data: {data}")
    """
    data format:
        'a' (action): [PICK_NEW_TORRENT|ADD_NEW_TORRENT|MANAGE_TORRENT]
        't_id' (torrent id)
        't_type' (torrent type): [movie|tv show|other] - for ADD_NEW_TORRENT
        'o' (operation): [start|pause|delete] - for MANAGE_TORRENT
    """
    if data["a"] == PICK_NEW_TORRENT:
        update.callback_query.answer(text="Got it! What type of download is it?")
        update.callback_query.message.edit_reply_markup(reply_markup=SELECT_TORRENT_TYPE_INLINE_KEYBOARD)

    elif data["a"] == ADD_NEW_TORRENT:
        torrent_url = prepare_url(html.unescape(update["callback_query"]["message"]["text"].split(". ")[1]))
        torrent_type = data["t_type"]
        logger.info(f"torrent_url: {torrent_url}\ntorrent_type: {torrent_type}")

        t = add_torrent(torrent_url, torrent_type)

        update.callback_query.answer()
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="start download",
                                    callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                            "o": "start",
                                                            "t_id": t.id})),
                InlineKeyboardButton(text="remove",
                                    callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                            "o": "delete",
                                                            "t_id": t.id}))]
        ])
        update.callback_query.message.edit_text(f"✓ - {torrent_type}. {torrent_url}")
        update.callback_query.message.edit_reply_markup(reply_markup=reply_markup)
        update.callback_query.message.reply_text(f"Added {t.name}!", reply_markup=reply_markup)

        return MAIN

    elif data["a"] == MANAGE_TORRENT:
        if data["o"] == "start":
            manage_torrent(data["t_id"], "start")
            update.callback_query.answer("Download started!")
            update.callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="pause download",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "pause",
                                                                "t_id": data["t_id"]})),
                 InlineKeyboardButton(text="remove",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete",
                                                                "t_id": data["t_id"]}))]
            ]))
        elif data["o"] == "pause":
            manage_torrent(data["t_id"], "pause")
            update.callback_query.answer("Download paused!")
            update.callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="start download",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "start",
                                                                "t_id": data["t_id"]})),
                 InlineKeyboardButton(text="remove",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete",
                                                                "t_id": data["t_id"]}))]
            ]))
        elif data["o"] == "delete":
            update.callback_query.answer()
            update.callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="remove data too",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete_data",
                                                                "t_id": data["t_id"]})),
                 InlineKeyboardButton(text="keep data",
                                      callback_data=json.dumps({"a": MANAGE_TORRENT,
                                                                "o": "delete_no_data",
                                                                "t_id": data["t_id"]}))]
            ]))
        elif data["o"] == "delete_data":
            manage_torrent(data["t_id"], "delete", True)
            update.callback_query.answer("Download and data deleted!")
            message = update["callback_query"]["message"]["text"].split(". ")[1]
            update.callback_query.message.edit_reply_markup(reply_markup=None)
            update.callback_query.message.edit_text(f"X - {message}")
        elif data["o"] == "delete_no_data":
            manage_torrent(data["t_id"], "delete", False)
            update.callback_query.answer("Download deleted, data kept!")
            message = update["callback_query"]["message"]["text"].split(". ")[1]
            update.callback_query.message.edit_reply_markup(reply_markup=None)
            update.callback_query.message.edit_text(f"X - {message}")


def main():
    # Create the Updater and pass it your bot"s token.
    updater = Updater(TORRENTBOT_TOKEN, use_context=True)

    updater.start_webhook(listen="0.0.0.0", port=3520, url_path=TORRENTBOT_TOKEN)
    updater.bot.set_webhook(TELEGRAM_WEBHOOK_ENDPOINT + TORRENTBOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Add conversation handler with the states MAIN, DOWNLOAD, and TORRENT_STATUS
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start, Filters.user(user_id=TELEGRAM_USERID_LIST))],

        states={
            MAIN: [MessageHandler(Filters.regex(TORRENT_URL_REGEX) | Filters.regex(MAGNET_URI_REGEX),
                                  handle_torrent_magnet_link),
                   MessageHandler(Filters.regex(URL_REGEX),
                                  get_links_from_webpage),
                   MessageHandler(Filters.regex("^(Downloading|Seeding|Paused)$"),
                                  check_torrents),
                   ],
        },

        fallbacks=[MessageHandler(Filters.regex("^Cancel$"), cancel)]
    )

    callback_handler = CallbackQueryHandler(
        handle_callback
    )

    dp.add_handler(conv_handler)
    dp.add_handler(callback_handler)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == "__main__":
    main()
