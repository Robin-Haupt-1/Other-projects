from shared.todoist_wrapper import Todoist, Item
from datetime import datetime
import time
import os
import sys
from shared.classes import DaemonTask
from termcolor import colored
import pickle
from urllib.parse import quote
import time
from dataclasses import dataclass
from requests.exceptions import ConnectionError
from shared.classes import ActivityMonitor
from shared.utils import os_name, project_dir
import sqlite3
from typing import Callable
import webbrowser

todoist = Todoist()


class ListDaemon(DaemonTask):
    """Open new and old entries of a list in the browser, with specified search engines"""

    @dataclass
    class List:
        project_id: int
        callsign: str
        search_engines: [str]
        interval: int = 10
        age_days: int = 3
        pad_to: int = 2
        do_separate_joined: bool = True
        extra_should_run: Callable[
            [], bool] = lambda: True  # get's called on top of regular should_run for list specific condition checking
        evaluate_item: Callable[[Item], tuple[bool, bool]] = lambda item: (True,
                                                                           True)  # evaluate an item and decide whether to process it in this run. (Whether to see it at all, whether to consider it new)

    lists = {"Goodreads": List(project_id=2272605858, callsign="Goodreads", search_engines=[
        "https://www.goodreads.com/search/search?search_type=books&search[query]=%s"], do_separate_joined=False),
             "Deutsch": List(project_id=2252278976, callsign="Deutsch",
                             search_engines=["https://www.google.de/search?q=%s"]),
             "Englisch": List(project_id=2267806604, callsign="Englisch", search_engines=["https://www.dict.cc/?s=%s",
                                                                                          "https://dictionary.cambridge.org/de/worterbuch/englisch/%s"],
                              evaluate_item=lambda item: (True, 2158177824 not in item.item_dict["labels"]), pad_to=4),  # make sure ew entries aren't tagged with 'ew-alt'
             "Googlen": List(project_id=2273449705, callsign="Google",
                             search_engines=["https://www.google.de/search?q=%s"]),
             "Linux": List(project_id=2274245379, callsign="Linux",
                           search_engines=["https://www.google.de/search?q=%s"],
                           extra_should_run=lambda: os_name == "Linux"),
             "Windows": List(project_id=2274245362, callsign="Windows",
                             search_engines=["https://www.google.de/search?q=%s"],
                             extra_should_run=lambda: os_name == "Windows"),
             "Two days": List(project_id=2273797474, callsign="Two days",
                              search_engines=["https://www.google.de/search?q=%s"],
                              evaluate_item=lambda item: (item.age.days > 1, True), age_days=1000),
             "One day": List(project_id=2274830093, callsign="Two days",
                             search_engines=["https://www.google.de/search?q=%s"],
                             evaluate_item=lambda item: (item.age.days > 0, True), age_days=1000),
             # add: open on amazon, open url
             }

    def __init__(self, list_name: str, **kwargs):
        super(ListDaemon, self).__init__(**kwargs)
        list = self.lists[list_name]

        self.callsign = list.callsign
        self.interval = list.interval

        self.project_id = list.project_id
        self.age_days = list.age_days
        self.pad_to = list.pad_to
        self.do_separate_joined = list.do_separate_joined
        self.search_engines = list.search_engines
        self.idle_ran = False
        self.extra_should_run = list.extra_should_run
        self.evaluate_item = list.evaluate_item

    def task(self):
        if not self.extra_should_run():
            return
        self.separate_joined()
        # check if there new entries (young enough )
        all_entries = [item for item in self.items() if self.evaluate_item(item)[0]]
        new_entries = [i for i in all_entries if i.age.days < self.age_days and self.evaluate_item(i)[1]]

        if new_entries:
            self.log(f"{len(new_entries)} entries added in last {self.age_days} days")

        # if there are new entries or user is idle, pad them to desired number and show them in browser
        if new_entries or self.do_idle_run():
            if len(new_entries) < self.pad_to:
                self.log(f"Padding to {self.pad_to} entries")
                new_entries = all_entries[-self.pad_to:]
            # open the web sites
            for count, item in enumerate(new_entries):
                self.log(f"{count + 1}/{len(new_entries)} {item.content} ({item.age.days} days old) ")
                for search_engine in self.search_engines:
                    if not webbrowser.open(search_engine.replace("%s", quote(item.content)), autoraise=False):
                        raise Exception
                    time.sleep(1)
                todoist.api.items.get_by_id(item.id).complete()
            # Complete all shown items on Todoist servers
            self.log("Completing words on Todoist API...", end="\t")
            todoist.api.commit()
            print(colored("Done", "green"))

    def separate_joined(self):
        """ Split words joined with a dot into new items"""
        if not self.do_separate_joined:
            return
        for i in self.items():
            if "." in i.content:
                self.log(f"Joined item: {i.content}")
                for word in i.content.split("."):
                    if word:
                        todoist.api.items.add(word, project_id=self.project_id)
                todoist.api.items.get_by_id(i.id).complete()
                todoist.sync()

    def items(self):
        """Get all the projects items"""
        return todoist.items_by_project(self.project_id)

    def do_idle_run(self):
        """Return true if user has been idle for more than n seconds, but only once per idle period"""
        if not self.idle_ran and self.activity_monitor.idle_seconds() > 600:
            self.log("Doing idle run")
            self.idle_ran = True
            return True


class BookQuoteDaemon(DaemonTask):
    """Sort all items from projects containing book notes to sections in Sammelprojekten"""

    # Todo: move book quote sections if Sammelprojekt gets too full because new entries have been added to it's sections
    def __init__(self, parent_project=2264075774, project_color=45, **kwargs):
        super(BookQuoteDaemon, self).__init__(**kwargs)
        self.callsign = "Buchauszüge"
        self.interval = 10
        self.api = todoist.api
        self.state = todoist.state
        self.parent_project: int = parent_project
        self.project_color = project_color
        self.first_encountered_project = {}

    def task(self):
        # find all projects ending in "book" that have no parent project
        for project in [x for x in todoist.active_projects() if not x["parent_id"] and x["name"][-4:] == "book"]:

            # check if they've first been encountered at least 30 seconds ago (grant user time to create items after project creation)
            if project["id"] not in self.first_encountered_project:
                # Hasn't been encountered yet
                self.first_encountered_project[project["id"]] = datetime.now().timestamp()
                self.log(f"Skipping {project['name']}. Its too young")
                continue
            if (project_age := (datetime.now().timestamp()) - self.first_encountered_project[project["id"]]) < 30:
                # Isn't at least 30 seconds old
                self.log(f"Skipping {project['name']}. Its too young ({int(project_age)} s) ")
                continue

            # Determine which Sammelproject to create new section in
            # get the latest Sammelprojekt
            all_sammelprojekte = [x for x in todoist.active_projects() if x["parent_id"] == self.parent_project]
            sammelprojekt = all_sammelprojekte[-1]["id"]

            # Check if there is still room in this project
            if not (len(todoist.items_by_project(sammelprojekt)) < 200 and len(
                    todoist.sections_of_project(sammelprojekt)) < 18):
                # Create new project since old one is full
                name = "Buchauszüge " + str(len(all_sammelprojekte) + 1)
                self.log(f"Creating new Sammelprojekt '{name}'")
                self.api.projects.add(name, parent_id=self.parent_project, color=self.project_color)
                self.api.commit()
                sammelprojekt = [x["id"] for x in todoist.active_projects() if x["name"] == name][0]

            self.log(f"Sorting project '{project['name']}' ({todoist.project_item_count(project['id'])} items)",
                     end="\t")
            # Create new section
            section_name = project["name"][:-4]
            self.api.sections.add(section_name, project_id=sammelprojekt)
            self.api.commit()
            section_id = [x["id"] for x in todoist.active_sections() if
                          x["project_id"] == sammelprojekt and x["name"] == section_name][0]

            # Move all items to new section
            for x in [x for x in todoist.active_items() if x.project_id == project["id"]]:
                self.api.items.get_by_id(x.id).move(section_id=section_id)
            self.api.commit()
            # Archive now empty project
            self.api.projects.get_by_id(project["id"]).archive()
            self.api.commit()

            self.log("Done!", start="", color="green")


class UnusedProjects(DaemonTask):
    """Move all items from projects with few items and no recent activity to sections in Sammelprojekten"""

    def __init__(self, parent_project_name="Archivierte kleine Projekte", project_color=45, **kwargs):
        super(UnusedProjects, self).__init__(**kwargs)

        self.callsign = "Archiving"
        self.interval = 10
        self.api = todoist.api
        self.state = todoist.state
        self.parent_project: int = todoist.project_by_name(parent_project_name)
        self.parent_project: int = todoist.project_by_name(parent_project_name)
        self.project_color = project_color
        self.first_encountered_project = {}

    def task(self):
        # find all projects that have no parent project and not that many items but at least one and that have no tasks younger than 30 days
        for project in (to_sort := [x for x in todoist.active_projects() if
                                    not x["parent_id"] and (
                                            (items := todoist.project_item_count(x["id"])) < 30 and items) and not any(
                                        [x < 30 for x in [item.age.days for item in todoist.items_by_project(
                                            x["id"])]]) and not todoist.sections_of_project(x["id"])]):
            self.log(f"Projekte zu verarbeiten: {len(to_sort)}")
            self.log(f"Working on {project['name']} ({project['id']})")
            # Determine which Sammelproject to create new section in
            # get the latest Sammelprojekt
            all_sammelprojekte = [x for x in todoist.active_projects() if x["parent_id"] == self.parent_project]
            sammelprojekt = all_sammelprojekte[-1]["id"]
            self.log(f"Chose Sammelprojekt id {sammelprojekt}")
            # Check if there is still room in this project
            if not (len(todoist.items_by_project(sammelprojekt)) < 200 and len(
                    todoist.sections_of_project(sammelprojekt)) < 18):
                # Create new project since old one is full
                name = "Archivierte Projekte " + str(len(all_sammelprojekte) + 1)
                self.log(f"Creating new Sammelprojekt '{name}'")
                self.api.projects.add(name, parent_id=self.parent_project, color=self.project_color)
                self.api.commit()
                sammelprojekt = [x["id"] for x in todoist.active_projects() if x["name"] == name][0]
            assert sammelprojekt

            self.log(f"Sorting project '{project['name']}' ({todoist.project_item_count(project['id'])} items)",
                     end="\t")

            # Create new section
            section_name = project["name"]
            self.api.sections.add(section_name, project_id=sammelprojekt)
            self.api.commit()
            section_id = [x["id"] for x in todoist.active_sections() if
                          x["project_id"] == sammelprojekt and x["name"] == section_name][0]
            self.log(f"actual id of new section: {section_id}")
            assert section_id

            # Move all items to new section
            for x in [x for x in todoist.active_items() if x.project_id == project["id"]]:
                self.log(f"Moving item {x.content}")
                self.api.items.get_by_id(x.id).move(section_id=section_id)
            self.api.commit()

            # Delete now empty project
            self.log("Archiving project")
            self.api.projects.get_by_id(project["id"]).archive()
            self.api.commit()
            self.log("Done!", start="", color="green")


class SyncTodoistAPI(DaemonTask):
    def __init__(self, **kwargs):
        super(SyncTodoistAPI, self).__init__(**kwargs)

        self.callsign = "Sync Todoist"
        self.interval = 10

    def task(self):
        try:
            todoist.sync()
        except  ConnectionError:
            self.log("Can't synchronize Todoist API: No connection", color="red")
        except Exception as e:
            self.log(f"Can't synchronize Todoist API: {e}", start="", color="red")


class PickleBackupTodoistAPI(DaemonTask):
    """Once a day, save the API object to a file"""

    def __init__(self, filename: str = "Todoist API Backup %Y-%m-%d.PKL", **kwargs):
        """
        :param filename: the name for the file. can include datetime strftime placeholders
        """
        super(PickleBackupTodoistAPI, self).__init__(**kwargs)
        self.pickle_folder: str = os.path.join(project_dir, ".files", "Backup Todoist daily (PKL)")
        self.callsign = "Backup Todoist"
        self.interval = 3600
        self.filename = filename

    def task(self):
        filename = os.path.join(self.pickle_folder, datetime.now().strftime(self.filename))
        if os.path.isfile(filename):
            self.log(f"Skipping Todoist backup because file already exists: '{filename}'...", color="green")
            return
        self.log(f"Pickling Todoist API... writing to '{filename}'...", end="\t")
        pickle.dump(todoist, open(filename, "wb"))
        self.log("Done", start="", color="green")

    def should_run(self):
        return self.check_run_interval("daily")


class KindleImport(DaemonTask):
    """Import vocabulary from USB-connected kindle, store in ew Todoist project"""

    def __init__(self, filename: str = "Todoist API Backup %Y-%m-%d.PKL", **kwargs):
        """
        :param filename: the name for the file. can include datetime strftime placeholders
        """
        super(KindleImport, self).__init__(**kwargs)

        self.callsign = "Kindle Import"
        self.interval = 10
        self.kindle_file = r"Z:\system\vocabulary\vocab.db" if os_name == "Windows" else "/media/robin/Kindle/system/vocabulary/vocab.db"
        self.done_folder = os.path.join(project_dir, ".files", "kindle imported vocab")
        self.filename = filename
        self.project_id = 2274744021  # 2273641852
        self.load_imported()

    def task(self):
        # check if kindle is connected
        if not os.path.isfile(self.kindle_file):
            return
        # read kindle db
        con = sqlite3.connect(self.kindle_file)
        cur = con.cursor()
        all_words = cur.execute('SELECT stem,timestamp FROM WORDS ORDER BY timestamp')

        # create new word items with timestamps in seconds instead of milliseconds
        new_words = [{"word": word[0], "timestamp": word[1] / 1000} for word in all_words if
                     not word[0] in self.imported_words]
        con.close()

        if not new_words:
            self.log("No new words to import", to_file=False)
            return
        self.log(f'{len(new_words)} new words to import')
        for count, word in enumerate(new_words):
            # push new words to Todoist project.
            self.log(f"creating {word['word']}")
            # If the entry is too old, tag it with 'ew-alt' label (because it will be new on Todoist but they shouldn't automatically be opened by the ListDaemon)
            labels = [2158177824] if datetime.now().timestamp() - word["timestamp"] > 2 * 86400 else []
            # create new Todoist item
            todoist.api.items.add(content=word["word"], project_id=self.project_id, labels=labels)
            # commit after every 90 new items (100 is maximum per commit)
            self.log(count % 90)
            if count % 90 == 89:
                self.log("commiting")
                todoist.api.commit()
                todoist.api.sync()

        todoist.api.commit()
        todoist.api.sync()
        # save imported words to done_folder
        with open(os.path.join(self.done_folder, f"{datetime.now().strftime('%Y-%m-%d %H-%M-%S imported.txt')}"), "w+",
                  encoding="utf-8") as file:
            file.write("\n".join([x["word"] for x in new_words]))

        # refresh list of imported words
        self.load_imported()

    def load_imported(self):
        """load all the already imported words"""
        with os.scandir(self.done_folder) as files:
            files = [open(file.path, "r", encoding="utf-8").read().split("\n") for file in files]
            self.imported_words = list(set([x.strip() for file in files for x in file if (x and not x[0] == "#")]))
        self.task()

