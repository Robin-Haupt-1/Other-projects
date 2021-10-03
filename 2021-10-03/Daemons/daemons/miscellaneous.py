import datetime
import os
import requests

from shared.classes import DaemonTask
from shared.utils import string_to_filename, os_name, has_internet_connection, public_ip, public_ip_info


class MonitorVPN(DaemonTask):
    """Monitor the public ip / internet connection and log changes"""

    def __init__(self, **kwargs):
        super(MonitorVPN, self).__init__(**kwargs)
        self.need_internet = False  # make the daemon run even where there is no internet connection
        self.callsign = "VPN"
        self.interval = 5
        self.ip = None  # stores either False for no internet connection, or the public ip
        self.ip_info = {}  # store country information from ipinfo.com for each known ip
        # announce daemon first run
        self.log("Daemon started", color="green")

    def task(self):
        # save reference to last state
        old_ip = self.ip

        # check internet connection and get ip
        ip = public_ip() if has_internet_connection() else False

        # When public ip or connection status changes, log it
        if ip != old_ip:
            if ip:
                # the is internet but the ip has changed
                if ip not in self.ip_info:
                    self.ip_info[ip] = public_ip_info()
                self.log(f"Connected as {ip} ({self.ip_info[ip]['country']} / {self.ip_info[ip]['city']}) ", color="green")
            else:
                # no internet connection
                self.log(f"No internet connection", color="red")
        self.ip = ip


class DictccCrawler(DaemonTask):
    """crawl the dict.cc list and store any new entries as text files"""

    def __init__(self, list_name: str, **kwargs):
        super(DictccCrawler, self).__init__(**kwargs)
        self.callsign = "Dict.cc"
        self.interval = 5

        self.usercookie = "xxxxxxxxxxxxxxxxx"
        self.FOLDER = r"/hdd/Software Engineering/.files/2021-09-23 Dict.cc und Cambridge Importer" if os_name == "Linux" else r"E:\.files\2021-09-23 Dict.cc und Cambridge Importer"

        # load list file url dependent on list name
        self.url = {"Wörter": 'https://deen.my.dict.cc/export/xxxx/EN-DE-xxxxx.txt',
                    'Redewendungen': 'https://deen.my.dict.cc/export/xxxxx/EN-DE-xxxxx.txt'}[list_name]

        # setup and load paths and files
        self.destination_dir = os.path.join(self.FOLDER, "dict cc crawled vocabulary", list_name)
        self.last_state_file_path = os.path.join(self.FOLDER, f"crawler laststate {list_name}.txt")
        self.last_list = [x.strip() for x in open(self.last_state_file_path, "r", encoding="utf-8").read().split("\n")
                          if len(x.strip()) > 0]

    def task(self):

        # download the current list of stored vocabulary
        list = requests.get(self.url, cookies={"u5ercookie": self.usercookie})

        # abort if the session cookie has expired or the request status code is bad
        if list.status_code != 200 or "auch möglich, eigene Vokabeln einzutippen" in list.text:
            self.log(f"skipping, status code {str(list.status_code)}")
            raise Exception("Session expired")

        # extract all the new terms that haven't been crawled in the last run
        current = [x.strip() for x in list.text.split("\n")]
        new = [x for x in current if x not in self.last_list]

        if new:
            self.log(f"New words: ")
            # Save new entries as seperate text files
            for count, x in enumerate(new):
                self.log(f"\t{x}")
                filename = string_to_filename(x.replace("\t", " - "))[:50]
                with open(os.path.join(self.destination_dir, f'{datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")} {count}   -   {filename}.txt' + "   -   " + filename + ".txt"), "w+", encoding="utf-8") as file:
                    file.write(x)

            # save the new state

            self.last_list = self.last_list + new
            with open(self.last_state_file_path, "w+", encoding="utf-8") as file:
                file.write("\n".join(self.last_list))
