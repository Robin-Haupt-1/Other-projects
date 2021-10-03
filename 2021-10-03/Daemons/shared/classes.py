from datetime import datetime as datetime2
from termcolor import colored
import datetime
import traceback
import os
from shared.utils import has_internet_connection, active_window, get_user_idle_duration


class DaemonTask:
    """Parent class of all daemons that handles running them at certain intervals and formatting the log output"""

    def __init__(self, callsign=None, interval=None, silent=True, need_internet=True):
        self.callsign = callsign
        self.interval = interval
        self.last_run = 0
        self.last_task_run = 0
        self.silent = silent
        self.need_internet = need_internet
        self.activity_monitor = None

    def run(self):
        # run every %interval seconds if self.should_run is true (default)

        # skip this run if there is no internet but it's needed
        if self.need_internet and not has_internet_connection():
            return

        if (self.interval and (now := datetime2.now().timestamp()) - self.last_run) > self.interval:
            if not self.should_run():
                # skip this run because the algorithm says so
                self.last_run = now
                return
            if not self.silent:
                print(f"Führe {self.callsign.upper()} aus")
            try:
                self.task()
                self.last_task_run = datetime2.now().timestamp()
            except Exception as e:
                print(e)
                print(traceback.format_exc())
            self.last_run = now
            return True

    def log(self, text, start=None, end="\n", color="cyan", start_color="cyan", to_file=True):
        # create folder for today's logs if it doesn't exist
        folder = f".log/{datetime2.now().strftime('%Y-%m-%d')}"
        os.makedirs(folder, exist_ok=True)

        # print nicely formatted log to stdout
        time = datetime2.now().strftime('%H:%M:%S')
        if start is None:
            start = "{:<10} {:<13}\t".format(time, f"[{self.callsign.upper()}]")
        print(f"{colored(start, start_color)}{colored(text, color)}", end=end)

        # save log entry to log file if enabled
        if to_file:
            with open(f".log/{datetime2.now().strftime('%Y-%m-%d')}/{self.callsign.upper()} {datetime2.now().strftime('%Y-%m-%d')}.txt", "a+", encoding="utf-8") as file:
                file.write(f"{time}\t{text}\n")

    def task(self):
        print("task on Daemontask class called")

    def should_run(self):
        """Can be overwritten to modify the run times with an algorithm"""
        return True

    def check_run_interval(self, interval="daily"):
        """return True once every %interval
        Todo: save information in file to allow restarting the daemon without running it twice
        Todo: allow keeping seperate intervals for different subtasks"""

        if interval == "daily":
            # return True only once a day

            # check if task wasn't last run today
            if not (datetime2.now().date() == datetime.date.fromtimestamp(self.last_task_run)):
                # set new "task last run" timestamp to now

                return True

            return False

    def set_activity_monitor(self, activity_monitor: any):
        """Set which activity monitor instance to use"""
        self.activity_monitor = activity_monitor


class ActivityMonitor(DaemonTask):
    """keep track of what the user is doing and analyze it to help daemons act according to user activity"""

    def __init__(self, **kwargs):
        super(ActivityMonitor, self).__init__(**kwargs)
        self.callsign = "Activity"
        self.interval = 1
        self.need_internet = False
        self.activity_log = []  # every second, the title of the active window is stored in here
        self.activity_indicators = {"movie": ["MPC", "VLC media player"],
                                    "coding": [".py", "Visual Studio Code"],
                                    "gaming": ["Minecraft"]}

    def task(self):
        """truncate stored activity and add current active window to record"""
        # Todo: check whether title counts as activity type and store that information. save tons of cpu

        # truncate activity log (only keep records of last 20 minutes)
        self.activity_log = self.activity_log[int(-20 * (60 / self.interval)):]
        self.activity_log.append(active_window())

    def evaluate_activity(self, activities: str = None, percentage: int = 50, minutes=20):
        """Check whether the given activity has been preeminent within supervised time period
        :param activities:  the activity category to check for seperated by comma as string (gaming, movie or coding) or "all"
        :param percentage: minimum percentage of time that activity must have taken up
        :param minutes: the duration of activity tracking data to check against"""

        if activities == "all":
            window_titles = [activity for category in self.activity_indicators.values() for activity in category]
        else:
            window_titles = [window_title for activity_name in activities.split(",") for window_title in self.activity_indicators[activity_name]]

        monitor_period = self.activity_log[int(-minutes * (60 / self.interval)):]

        return sum([1 if any([x in _active_window for x in window_titles]) else 0 for _active_window in monitor_period]) > len(self.activity_log) * (percentage / 100)

    def idle_seconds(self):
        """Return the seconds since last user input"""
        return get_user_idle_duration()
