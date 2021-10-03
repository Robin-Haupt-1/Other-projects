import time
import datetime
from termcolor import colored
from datetime import datetime as datetime2
from todoist.api import TodoistAPI
import pickle
import os
import time
from requests.exceptions import ConnectionError

from shared.utils import wait_for_internet_connection, project_dir, os_name


def get_todoist() -> TodoistAPI:
    """try to load the pickled API or create a new instance"""
    wait_for_internet_connection()
    pickle_file = os.path.join(project_dir, ".files", "todoist-api.pkl" if os_name == "Windows" else "todoist-api-linux.pkl")

    # try loading the pickled file and syncing the API
    if os.path.isfile(pickle_file):
        while True:
            try:
                print("Loading pickled Todoist API...", end="\t")
                api = pickle.load(open(pickle_file, "rb"))
                api.sync()

                # save freshly synced API to file for next run
                pickle.dump(api, open(pickle_file, "wb"))
                print(colored("Success!", "green"))
                return api
            except ConnectionError:
                # try again if the connection failed
                time.sleep(1)
                continue
            except Exception as e:
                # the file must be broken. abort
                print(f"Error: {e}")
                break

    # build and sync a new TodoistAPI instance
    start = datetime2.now().timestamp()
    print("Lade Todoist API neu")
    api = TodoistAPI('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    api.sync()
    print(f"Todoist API neu geladen, dauerte {(datetime2.now().timestamp() - start)} s")

    # save freshly synced API to file for next run
    pickle.dump(api, open(pickle_file, "wb"))
    return api


class Item:
    """Represents an item, offering easier access to the most important attributes and the item's age"""

    def __init__(self, item_dict):
        # copy over important item attributes
        self.content: str = item_dict["content"]
        self.id = item_dict["id"]
        self.section_id = item_dict["section_id"]
        self.project_id = item_dict["project_id"]
        self.item_dict = item_dict

        # Calculate age
        item_created = time.mktime(datetime.datetime.strptime(item_dict["date_added"], "%Y-%m-%dT%H:%M:%SZ").timetuple())
        self.age = datetime.timedelta(seconds=(datetime.datetime.now().timestamp() - item_created))

    def __str__(self):
        return f"Content: {self.content}"


class Todoist:
    """Wrapper for the official TodoistAPI instance"""

    def __init__(self):
        self.api = get_todoist()
        self.state = self.api.state
        # create instance attributes
        self.project_names, self._active_items, self.deleted_items = (None, None, None)
        self.cache()

    def sync(self):
        """commit any changes and sync the API"""
        self.api.commit()
        self.api.sync()
        self.cache()

    def cache(self):
        """After every sync, create new indexes / abstractions so they don't have to be created everytime a function that uses them is called"""
        self.project_names = dict([(project["name"], project["id"]) for project in
                                   self.active_projects()])  # dict mapping every project name to its id
        self._active_items = [Item(x) for x in self.state["items"] if x["is_deleted"] == 0 and x["checked"] == 0]

        self.deleted_items = [Item(x) for x in self.state["items"] if x["is_deleted"] == 1 or x["checked"] == 1]

    # Projects

    def list_all_projects(self):
        """Print all project's id and name"""
        for p in self.state["projects"]:
            print(p["id"], p["name"])

    def active_projects(self):
        """Return all active projects"""
        return [x for x in self.state["projects"] if not (x["is_archived"] or x["is_deleted"])]

    def deleted_projects(self):
        """Return all deleted projects"""
        return [x for x in self.state["projects"] if x["is_deleted"]]

    def archived_projects(self):
        """Return all archived projects"""
        return [x for x in self.state["projects"] if x["is_archived"]]

    def project_by_name(self, project_name: str):
        """Returns the id of the given project"""
        return self.project_names[project_name]

    def project_item_count(self, project_id: int):
        """@:return the number of active items in the project"""
        return len(self.items_by_project(project_id))

    # Sections

    def list_all_sections(self):
        """for every section, print id, name and project id"""
        for s in self.state["sections"]:
            print(s["id"], s["name"], "project:", s["project_id"])

    def active_sections(self):
        """Return all active sections"""
        return [x for x in self.state["sections"] if x["is_deleted"] == False and x["is_archived"] == False]

    def sections_of_project(self, project_id):
        """Return all section of given project id"""
        return [x for x in self.active_sections() if x["project_id"] == project_id]

    # Items

    def all_items(self) -> [Item]:
        """Return all items, active and deleted"""

        return self._active_items + self.deleted_items

    def active_items(self) -> [Item]:
        """Get all active items"""
        return self._active_items

    def items_by_project(self, project_id: int) -> [Item]:
        """Returns the active items in the project"""
        return [x for x in self.active_items() if x.project_id == project_id]

    # labels

    def label_dict(self):
        """Return a dict mapping each label id onto it's name"""
        return dict([(label["id"], label["name"]) for label in self.api.state["labels"]])
