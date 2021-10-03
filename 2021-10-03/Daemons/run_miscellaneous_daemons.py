import time
from shared.classes import ActivityMonitor
from daemons.miscellaneous import DictccCrawler, MonitorVPN

daemons = [DictccCrawler(list_name="Wörter"), MonitorVPN()]

if __name__ == "__main__":
    activity_monitor = ActivityMonitor()
    # tell all daemons to use the same ActivityMonitor instance
    [daemon.set_activity_monitor(activity_monitor) for daemon in daemons]

    daemons.append(activity_monitor)
    while True:
        for daemon in daemons:
            daemon.run()
        time.sleep(1)
