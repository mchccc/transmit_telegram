from transmission_rpc import Client
from secrets import (TRANSMISSION_ADDRESS, TRANSMISSION_PORT,
                     TRANSMISSION_USERNAME, TRANSMISSION_PASSWORD)


FIELDS = ["id", "name", "addedDate", "status",
          "eta", "peersConnected", "percentDone", "sizeWhenDone", "leftUntilDone",
          "rateDownload", "rateUpload", "uploadRatio"]


def _get_client():
    c = Client(host=TRANSMISSION_ADDRESS, port=TRANSMISSION_PORT,
               username=TRANSMISSION_USERNAME, password=TRANSMISSION_PASSWORD)
    return c


def parse_category(category):
    if category.lower() == "movie":
        return "/movies"
    elif category.lower() == "tv show":
        return "/tvshows"
    else:
        return "/other"


def add_torrent(url, category):
    c = _get_client()
    destination = parse_category(category)
    t = c.add_torrent(url, download_dir=destination, paused=True)
    return t


def get_downloading_torrents():
    c = _get_client()
    torrents = c.get_torrents(arguments=FIELDS)
    torrents = [t for t in torrents if t.status == "downloading"]
    return torrents


def get_seeding_torrents():
    c = _get_client()
    torrents = c.get_torrents(arguments=FIELDS)
    torrents = [t for t in torrents if t.status == "seeding"]
    return torrents


def get_paused_torrents():
    c = _get_client()
    torrents = c.get_torrents(arguments=FIELDS)
    torrents = [t for t in torrents if t.status in ["stopped", "check pending", "checking"]]
    return torrents


def get_torrent(torrent_id):
    c = _get_client()
    torrent = c.get_torrent(torrent_id, arguments=["id", "name"])
    return torrent


def manage_torrent(torrent_id, operation, remove_data=False):
    c = _get_client()
    if operation == "start":
        c.start_torrent(torrent_id)
    elif operation == "pause":
        c.stop_torrent(torrent_id)
    if operation == "delete":
        c.remove_torrent(torrent_id, delete_data=remove_data)
