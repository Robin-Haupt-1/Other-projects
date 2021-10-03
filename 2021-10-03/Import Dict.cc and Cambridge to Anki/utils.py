import requests
import re
import urllib.parse
import time
import socket
import os
import urllib.parse
import urllib.request
from .constants import DONE_FOLDER
from .lib import termcolor
import datetime
from aqt import mw
import anki.consts


def log(text, start=None, end="\n", color="cyan", start_color="cyan"):
    """Print colorful log to stdout"""
    if start is None:
        start = "{:<10} {:<13}\t".format(datetime.datetime.now().strftime('%H:%M:%S'), f"[IMPORT CAMBRIDGE]")
    print(f"{termcolor.colored(start, start_color)}{termcolor.colored(text, color)}", end=end)


def load_url(url, silent=False):
    """Load a URL while sending an user-agent string to circumvent bot protection measures
    :param silent: whether to print about the event to stdout
    """
    try:
        if not silent:
            print(f'Downloading {url}')
        return requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36'}, timeout=120)

    except Exception as e:
        print("❌❌❌ Fehler in load_url!", e, url)


def scrub_word(word):
    """Remove annotations and parts of the term that aren't essential. Otherwise Cambridge or phrasefinder might not recognize it"""
    scrubbed = word.split("\t")[0].strip()

    # Cut out these strings:
    cut = ["sth.", "sb.", " from ", " into ", " with "]
    for x in cut:
        scrubbed = scrubbed.replace(x, "")

    # Cut off anything after these strings:
    split = ["[", "{", "<", " for ", " to ", " of "]
    for x in split:
        scrubbed = scrubbed.split(x)[0]

    # cut off these strings if they occur at the very end
    end = [" to", " up", " into", " on", " upon", " off", " (off)", " about", " back"]
    for x in end:
        if scrubbed[-len(x):] == x:
            scrubbed = scrubbed[:-len(x)].strip()

    # cut off these strings if they occur at the very beginning of the term
    start = ["to ", "make ", "a ", "be "]
    for x in start:
        if scrubbed[:len(x)] == x:
            scrubbed = scrubbed[len(x):].strip()

    # Remove any special characters
    scrubbed = re.sub("[^abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZé '-]", '', scrubbed).strip()

    return scrubbed


def get_phrasefinder(en):
    """Use the phrasefinder.io API to determine how common an english word is"""
    params = {'corpus': 'eng-us', 'query': urllib.parse.quote(en), 'topk': 20, 'format': 'tsv'}
    params = '&'.join('{}={}'.format(name, value) for name, value in params.items())
    try:
        response = requests.get('https://api.phrasefinder.io/search?' + params)
        return int(response.text.split("\t")[1])
    except Exception as e:
        # If the word can't be found, return 0
        return 0


def has_internet_connection(host="8.8.8.8", port=53, timeout=3):
    """Try connecting to the Google DNS server to check internet connectivity"""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False


def wait_for_internet_connection():
    """Try connecting to the Google DNS server to check internet connectivity. Wait until there is connectivity"""
    while not has_internet_connection():
        print("Waiting for internet connection")
        time.sleep(1)
    return True


def all_imported_words():
    """Return all words that have already been imported into Anki"""
    with os.scandir(DONE_FOLDER) as files:
        files = [open(file.path, "r", encoding="utf-8").read().split("\n") for file in files]
        words = [x.strip() for file in files for x in file if (x and not x[0] == "#")]
        return list(set(words))


def update_tampermonkey_list():
    """Refresh the list of all imported words that the tampermonkey script reads"""
    with open(r"/opt/lampp/htdocs/imported dict.cc.txt", "w+", encoding="utf-8") as file:
        file.write("\n".join(all_imported_words()))


def unsuspend_new_cards():
    """unsuspend ew that have been imported 3 days ago or earlier and had been automatically suspended"""
    # reactivate common and rare words after different time intervals
    normal_cards = [mw.col.get_card(card_id) for card_id in mw.col.find_cards('"deck:All::Audio::Sprachen::🇺🇸 Englisch::_New" is:suspended is:new')]
    normal_cards = [card for card in normal_cards if datetime.datetime.now().timestamp() - card.mod > 3 * 86400]
    rare_cards = [mw.col.get_card(card_id) for card_id in mw.col.find_cards('"deck:All::Audio::Sprachen::🇺🇸 Englisch::_New (rare)" is:suspended is:new')]
    rare_cards = [card for card in rare_cards if datetime.datetime.now().timestamp() - card.mod > 6 * 86400]

    if not (normal_cards or rare_cards):
        return

    log(f"{len(normal_cards)} new common and {len(rare_cards)} new rare cards to unsuspend")
    log(f"Card ids: {normal_cards + rare_cards}")
    for card in normal_cards + rare_cards:
        card.queue = anki.consts.QUEUE_TYPE_NEW
        card.flush()
