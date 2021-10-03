from datetime import datetime as datetime2
import datetime
from shared.classes import DaemonTask, ActivityMonitor
from shared.utils import string_from_timedelta
import requests
import json


class HueInterface(DaemonTask):
    """Interface to the hue bridge"""

    def __init__(self, **kwargs):
        super(HueInterface, self).__init__(**kwargs)
        self.callsign = "Hue interface"
        self.interval = 3600

        self.BRIDGE_URL = "http://192.168.188.21/api/2SsmABIFNNdjguwxdRbg-xxxxxxxxxxxxxxxxxxxxxx/"
        self.lights_on_time = (12, 0)
        self.evening_time = (12, 0)
        self.get_daytime_time_bounds()

    # Methods to interact with schedules

    # loading schedules

    def load_schedules(self):
        """Load and return json of all schedules from the bridge"""
        response = requests.get(self.BRIDGE_URL + "schedules").text
        schedules = json.loads(response)
        return schedules

    def load_schedule(self, name: str):
        """Load schedule identified by name"""
        schedules = dict([(schedule["name"], schedule) for schedule in self.load_schedules().values()])
        return schedules[name]

    def get_schedule_time(self, name: str) -> (int, int):
        """Return (hour, minute) tuple of schedules localtime"""
        schedule_time = datetime2.strptime(self.load_schedule(name)["localtime"], "W127/T%H:%M:%S")
        return (schedule_time.hour, schedule_time.minute)

    def list_schedules(self):
        """print all schedules in table format"""

        schedules = [[schedule["name"], schedule["localtime"].replace("W127/T", "")[:-3], f'{int(schedule["command"]["body"]["transitiontime"] / 10)} s', f'{schedule["command"]["address"].split("/")[-2]}'] for schedule in
                     self.load_schedules().values()]

        # print table header
        row_format = "{: ^30} {: ^25} {: ^25} {: ^25}"
        self.log(row_format.format("Name", "Zeit", "transitiontime", "group"), color="yellow")
        self.log("-" * 105, color="yellow")

        # load schedules and print them sorted by execution time

        [self.log(row_format.format(*row), color="yellow") for row in sorted(schedules, key=lambda x: x[1])]

    def get_daytime_time_bounds(self):
        """initialize variables for checking if it's the right time to auto-adjust the lights based on user behaviour.
        only load them once so as not to overtax the bridge"""
        try:
            self.lights_on_time = self.get_schedule_time("Morgens Zimmer an (S)")
            self.evening_time = self.get_schedule_time("Warmes Licht am Abend (B)")
        except:
            pass

    # creating schedules

    def create_schedule(self, schedule: dict):
        """create a single predefined schedules on the bridge"""
        url = self.BRIDGE_URL + "schedules"
        return_ = requests.post(url, data=json.dumps(schedule)).text
        if "success" not in return_:
            self.log(f"Error while creating new schedule: {return_}", color="red")
            raise Exception(return_)

    def create_schedules(self, schedules: []):
        """create any number of predefined schedules on the bridge
        Todo: use create_schedule"""
        url = self.BRIDGE_URL + "schedules"
        for s in schedules:
            return_ = requests.post(url, data=json.dumps(s)).text
            if "success" not in return_:
                self.log(f"Error while creating new schedules: {return_}")
                raise Exception(return_)

    # deleting schedules

    def delete_all_schedules(self):
        """Delete all schedules on the bridge"""
        schedules = self.load_schedules()
        for sched in schedules.keys():
            return_ = requests.delete(self.BRIDGE_URL + "schedules/" + sched).text
            if "success" not in return_:
                self.log(f"Error while deleting all schedules: {return_}", color="red")
                raise Exception(return_)

    def group_any_on(self, group: int):
        return_ = requests.get(self.BRIDGE_URL + "groups").text
        json_ = json.loads(return_)
        # print(json_)
        return json_[str(group)]["state"]["any_on"]

    # Other methods

    def activate_scene(self, group: int, scene: str = None, transitiontime: int = 80, on=True):
        """Activate the given scene. Scene identified by its id, not name"""
        if not on:
            body = {"on": False}
        else:
            body = {"transitiontime": transitiontime, "scene": scene}

        if "success" not in (return_ := requests.put(self.BRIDGE_URL + f"groups/{group}/action", data=json.dumps(body)).text):
            self.log(f"Error while activating scene:{return_}", color="red")
            raise Exception(return_)

    def is_daytime(self):
        """True if it's not too early or late for cold lights"""
        now_time = datetime2.now()
        now_time = (now_time.hour, now_time.minute)
        if self.lights_on_time < now_time < self.evening_time:
            return True


class HueAdjuster(DaemonTask):
    """adjust all schedules to a new timetable in incremental daily steps.
    Todo: - synchronized with sunrise time; also incrementally adjust sleep duration"""

    def __init__(self, hue: HueInterface, wake_up_time: (int, int) = (8, 0), **kwargs, ):
        super(HueAdjuster, self).__init__(**kwargs)
        self.callsign = "Hue Adjuster"
        self.interval = 3600
        self.hue = hue
        self.maximum_routine_shift_per_day = 500  # minutes
        self.wake_up_time = datetime.timedelta(hours=wake_up_time[0], minutes=wake_up_time[1])

    def task(self):
        # define constants

        BETT_SCENES = {"wake-up light 1 hell": "3JERH-2MORtmaEp", "Nur zur Decke an": "NBHXRBhiuxMJ4pv", "Entspannen hell 3 100": "08Xm6VWSHybwM-M", "Aus": 0}

        SCHREIBTISCH_SCENES = {"Mix duo": "-MivIo8Ca5-Z4jm", "Entspannen hell": "0CE3cRwgHU33aTE", "Aus": 0, "Schreibtisch 1 aus": "AWwhnAo6xwCy1us", "Schreibtisch 2 aus": "FGooExO6DoSgEOv", "Schreibtisch 3 aus": "SVykakQIEVQaiMO",
                               "Schreibtisch 4 aus": "9n5Ego-61HWMYlx", "Schreibtisch 5 aus": "HkKPmXVMIe1qWrz", "warm 20 p und rot": "fa-e-CQHa-GeOKD", "nur rot": "-x3skD0nMOpoqzS", }
        SOFORT_SECONDS = 100
        FIFTEEN_MINUTES = 9000
        TEN_MINUTES = 6000
        FIVE_MINUTES = 3000

        # calculate new schedule times
        # calculate new wake up time. this must only be adjusted in small incremental steps
        old_wake_up_time = self.hue.get_schedule_time("Morgens Wakeuplight")

        # calculate total minutes after midnight for old and new wake up times
        old_wake_up_time = old_wake_up_time[0] * 60 + old_wake_up_time[1]
        new_wake_up_time = self.wake_up_time.total_seconds()/60

        # check if the difference between old and new wake up time is larger than allowed
        if abs(new_wake_up_time - old_wake_up_time) > self.maximum_routine_shift_per_day:
            new_wake_up_time = old_wake_up_time - self.maximum_routine_shift_per_day if new_wake_up_time < old_wake_up_time else old_wake_up_time + self.maximum_routine_shift_per_day
        # create new timedelta
        self.wake_up_time = datetime.timedelta(minutes=new_wake_up_time)

        sleep_duration = datetime.timedelta(hours=9, minutes=40)
        wachzeit_delta = datetime.timedelta(hours=24) - sleep_duration

        all_lights_on_time = self.wake_up_time + datetime.timedelta(minutes=16)
        lights_out_time = self.wake_up_time + wachzeit_delta + datetime.timedelta(minutes=1)
        warmes_licht_am_abend_time = lights_out_time - datetime.timedelta(hours=2, minutes=30)

        bed_countdown_step = 21  # minutes
        bed_countdown_start = (6 * bed_countdown_step + 1)
        bed_countdown_times = dict([(count + 1, lights_out_time - datetime.timedelta(minutes=bed_countdown_start) + (count * datetime.timedelta(minutes=bed_countdown_step))) for count in range(7)])

        b = BETT_SCENES
        new_schedules_bett = [["Morgens Wakeuplight", b["wake-up light 1 hell"], FIFTEEN_MINUTES, self.wake_up_time], ["Morgens Zimmer an (B)", b["Nur zur Decke an"], TEN_MINUTES, all_lights_on_time],
                              ["Warmes Licht am Abend (B)", b["Entspannen hell 3 100"], SOFORT_SECONDS, warmes_licht_am_abend_time], ["Lights out (B)", b["Aus"], 8*600, lights_out_time],
                              ["Bett Countdown 7 (B)", b["Nur zur Decke an"], SOFORT_SECONDS, bed_countdown_times[7]]]

        t = SCHREIBTISCH_SCENES
        new_schedules_schreibtisch = [["Morgens Zimmer an (S)", t["Mix duo"], TEN_MINUTES, all_lights_on_time], ["Warmes Licht am Abend (S)", t["Entspannen hell"], SOFORT_SECONDS, warmes_licht_am_abend_time],
                                      ["Lights out (S)", t["Aus"], 8*600, lights_out_time], ["Bett Countdown 1", t["Schreibtisch 1 aus"], SOFORT_SECONDS, bed_countdown_times[1]],
                                      ["Bett Countdown 2", t["Schreibtisch 2 aus"], SOFORT_SECONDS, bed_countdown_times[2]], ["Bett Countdown 3", t["Schreibtisch 3 aus"], SOFORT_SECONDS, bed_countdown_times[3]],
                                      ["Bett Countdown 4", t["Schreibtisch 4 aus"], SOFORT_SECONDS, bed_countdown_times[4]], ["Bett Countdown 5", t["Schreibtisch 5 aus"], SOFORT_SECONDS, bed_countdown_times[5]],
                                      ["Bett Countdown 6", t["warm 20 p und rot"], SOFORT_SECONDS, bed_countdown_times[6]], ["Bett Countdown 7 (S)", t["nur rot"], SOFORT_SECONDS, bed_countdown_times[7]]]

        # list schedules to be deleted
        self.log("Alte Routinen:")
        self.hue.list_schedules()

        # delete all schedules on the bridge
        self.log("Lösche alte Routinen...")
        self.hue.delete_all_schedules()

        # create new schedules
        self.log("Erstelle neue Routinen...")
        for x in ({"group": 3, "schedules": new_schedules_bett}, {"group": 1, "schedules": new_schedules_schreibtisch}):
            for name, scene, transitiontime, localtime in x["schedules"]:
                # create json to be sent to bridge
                body = {"transitiontime": transitiontime}

                if scene:  # will be 0 if lamps are to be turned off
                    body["scene"] = scene
                else:
                    body["on"] = False

                self.hue.create_schedule({"name": name, "command": {"address": f"/api/0/groups/{x['group']}/action", "method": "PUT", "body": body}, "localtime": "W127/T" + string_from_timedelta(localtime)})

        self.log("Neue Routinen:")
        self.hue.list_schedules()

    def should_run(self):
        return self.check_run_interval("daily")


class HueReactToMovieWatching(DaemonTask):
    """ When movie is being watched, make lights turn warm. When movie stops being watched, make them cold if its not too late in the day """
    def __init__(self, hue: HueInterface, **kwargs):
        super(HueReactToMovieWatching, self).__init__(**kwargs)
        self.hue = hue
        self.callsign = "Hue react"
        self.interval = 5
        self.lights_turned_warm = False

    def task(self):
        # check if its not too late to make lamps cold
        if not self.hue.is_daytime():
            return
        if not self.hue.group_any_on(1):
            # the lights have been manually turned off
            return

        if self.activity_monitor.evaluate_activity(activities="movie", minutes=10, percentage=2):
            if not self.lights_turned_warm:
                self.log("Movie is being watched. Turning lights warm...")
                self.hue.activate_scene(group=3, on=False)
                self.hue.activate_scene(group=1, scene="0CE3cRwgHU33aTE")
                self.lights_turned_warm = True
        else:
            # No movie is being watched. Check if lamps are still warm from previous watching and whether they should be returned to normal """
            if self.lights_turned_warm:
                self.log("No movie is being watched anymore. Turning lights cold...")
                self.hue.activate_scene(group=1, transitiontime=1000, scene="-MivIo8Ca5-Z4jm")
                self.lights_turned_warm = False
