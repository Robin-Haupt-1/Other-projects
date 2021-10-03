import time
from daemons.hue import *
from shared.classes import ActivityMonitor

hue = HueInterface()
daemons = [HueReactToMovieWatching(hue=hue), HueAdjuster(hue=hue)]

if __name__ == "__main__":
    activity_monitor = ActivityMonitor()
    # tell all daemons to use the same ActivityMonitor instance
    [daemon.set_activity_monitor(activity_monitor) for daemon in daemons]
    daemons.append(activity_monitor)
    while True:
        for daemon in daemons:
            daemon.run()
        time.sleep(1)
