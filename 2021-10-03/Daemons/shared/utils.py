import time
import socket
import sys
import os
import requests
import json


def public_ip() -> str:
    """Returns the public ip"""
    return requests.get("http://checkip.amazonaws.com/").text.strip()


def public_ip_info():
    """Returns info about the public ip from ipinfo.com"""
    print("getting ipinfo.com")
    url = 'http://ipinfo.io/json'
    response = requests.get(url).text
    data = json.loads(response)
    return data


def get_os_name():
    """Get the name of the running OS. Returns 'Linux', 'Windows' or 'Mac'"""
    if sys.platform in ['linux', 'linux2']:
        return "Linux"
    if sys.platform in ['Windows', 'win32', 'cygwin']:
        return "Windows"
    if sys.platform in ['Mac', 'darwin', 'os2', 'os2emx']:
        return "Mac"

    raise Exception(f"Unknown OS {sys.platform}")


# set project directory
project_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# save OS name to variable. It doesn't change
os_name = get_os_name()


# Set up functions for getting the active window title and the user idle duration

# create dummy functions to make IDE happy
def active_window() -> str:
    return "None"


def get_user_idle_duration() -> int:
    return 0


# create actual functions
if os_name == "Windows":

    from win32gui import GetWindowText, GetForegroundWindow
    from ctypes import Structure, windll, c_uint, sizeof, byref


    class LASTINPUTINFO(Structure):
        _fields_ = [
            ('cbSize', c_uint),
            ('dwTime', c_uint),
        ]


    def active_window() -> str:
        """Return title of the active window (empty string if nothing is in foreground"""
        return GetWindowText(GetForegroundWindow())


    def get_user_idle_duration() -> int:
        """return seconds since the last user activity"""
        lastInputInfo = LASTINPUTINFO()
        lastInputInfo.cbSize = sizeof(lastInputInfo)
        windll.user32.GetLastInputInfo(byref(lastInputInfo))
        millis = windll.kernel32.GetTickCount() - lastInputInfo.dwTime
        return millis / 1000.0

elif os_name == "Linux":
    def active_window():
        try:
            import wnck
        except ImportError:
            # print("wnck not installed")
            wnck = None
        if wnck is not None:
            screen = wnck.screen_get_default()
            screen.force_update()
            window = screen.get_active_window()
            if window is not None:
                pid = window.get_pid()
                with open("/proc/{pid}/cmdline".format(pid=pid)) as f:
                    active_window_name = f.read()
        else:
            try:
                from gi.repository import Gtk, Wnck
                gi = "Installed"
            except ImportError:
                print("gi.repository not installed")
                gi = None
            if gi is not None:
                Gtk.init([])  # necessary if not using a Gtk.main() loop
                screen = Wnck.Screen.get_default()
                screen.force_update()  # recommended per Wnck documentation
                active_window = screen.get_active_window()
                pid = active_window.get_pid()
                with open("/proc/{pid}/cmdline".format(pid=pid)) as f:
                    active_window_name = f.read()
        # print(active_window_name)
        return active_window_name


    def get_user_idle_duration() -> int:
        """idle duration for Linux not implemented yet"""
        return 0


def has_internet_connection(host="8.8.8.8", port=53, timeout=3) -> bool:
    """Try connecting to the Google DNS server to check internet connectivity"""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False


def wait_for_internet_connection(log_callback=None, silent=False) -> True:
    """Try connecting to the Google DNS server to check internet connectivity. Wait until there is connectivity
    :param log_callback: function to call with log text
    :param silent: if True, will not print to stdout but still print to log_callback"""

    while not has_internet_connection():
        if log_callback:
            log_callback("Waiting for internet connection")
        elif not silent:
            print("Waiting for internet connection")
        time.sleep(5)
    return True


def string_from_timedelta(tdelta) -> str:
    """convert timedelta to string (HH:MM:SS)"""

    hours, rem = divmod(tdelta.seconds, 3600)
    hours = str(hours)
    if len(hours) < 2:
        hours = "0" + hours
    minutes, seconds = divmod(rem, 60)
    minutes = str(minutes)
    if len(minutes) < 2:
        minutes = "0" + minutes
    seconds = str(seconds)
    if len(seconds) < 2:
        seconds = "0" + seconds

    return f"{hours}:{minutes}:{seconds}"


def string_to_filename(filename, raw=False):
    """if raw is true, will delete all illegal characters. Else will replace '?' with '¿' and all others with '-'"""
    illegal_characters_in_file_names = r'"/\*?<>|:'

    if raw:
        return ''.join(c for c in filename if c not in illegal_characters_in_file_names)

    for x in [["?", "¿"]] + [[x, "-"] for x in illegal_characters_in_file_names.replace("?", "")]:
        filename = filename.replace(x[0], x[1])
    return filename
