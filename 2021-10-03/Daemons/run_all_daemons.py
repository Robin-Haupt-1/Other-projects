import time
from shared.classes import ActivityMonitor
from run_hue_daemons import daemons as hue_daemons
from run_todoist_daemon import daemons as todoist_daemons
from run_miscellaneous_daemons import daemons as miscellaneous_daemons

daemons = todoist_daemons + miscellaneous_daemons + hue_daemons


# tell all daemons to use the same ActivityMonitor instance
activity_monitor = ActivityMonitor()
[daemon.set_activity_monitor(activity_monitor) for daemon in daemons]
daemons.append(activity_monitor)

while True:
    for daemon in daemons:
        daemon.run()
    time.sleep(1)
