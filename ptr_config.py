# -*- coding: utf-8 -*-
"""
Created on Fri Aug  2 11:57:41 2019
Updated 20220904 22:42WER

@authors: wrosing, mfitz
"""

import os
import pathlib
import sys
import socket

import glob

# This routine here removes all mention of previous configs from the path...
# for safety and local computer got clogged with all manner of configs in the path

path_removals = []
for q in range(len(sys.path)):
    if "ptr-wema" in sys.path[q] and "configs" in sys.path[q]:
        print("Removing old config path: " + str(sys.path[q]))
        path_removals.append(sys.path[q])

for remover in path_removals:
    sys.path.remove(remover)

try:
    # This module is imported before ptr_endpoints, so .env has not been read
    # yet and PTR_WEMA_SITE below would be invisible.
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:      # python-dotenv is optional
    pass

pathdone = 0

# An explicit override beats both discovery methods below, so a dev site can
# run on a machine that is not named after it:  PTR_WEMA_SITE=dev
_site_override = os.environ.get("PTR_WEMA_SITE")
if _site_override:
    sys.path.append(os.path.join(pathlib.Path().resolve(), "configs", _site_override.lower()))
    pathdone = 1

# First try to get the wemaname from a file in the directory above (..) ptr-observatory
cwd = str(pathlib.Path().resolve())
hwd = cwd.replace("ptr-wema", "")
wemaname_file = glob.glob(hwd + "wemaname*")


try:
    #breakpoint()
    if pathdone:
        raise IndexError("site already selected by PTR_WEMA_SITE")
    site_name = wemaname_file[0].split("wemaname")[1].split('.')[0]
    # print(
    #     "Adding new config path: "
    #     + str(os.path.join(pathlib.Path().resolve(), "configs", site_name))
    # )
    sys.path.append(os.path.join(pathlib.Path().resolve(), "configs", site_name))
    pathdone = 1
except (OSError, IndexError):
    print(
        "Could not find a wemaname* file in the directory above ptr-observatory \
        (e.g. wemanamesro).\n Trying another method..."
    )

if pathdone == 0:
    print("Attempting wemaname approach to config file...")

    # NB May be better to split on '-' and use first part of wemaname.
    # The hostname heuristic assumes a machine named after its site. Allow an
    # explicit override so a dev site can run on any box:  PTR_WEMA_SITE=dev
    host_site = os.environ.get("PTR_WEMA_SITE", socket.gethostname()[:3]).lower()

    #if host_site == "saf":
     #   host_site == "aro"  # NB NB THIS is a blatant hack. TODO Remove this

    # print(
    #     "Adding new config path: "
    #     + str(os.path.join(pathlib.Path().resolve(), "configs", host_site))
    # )
    sys.path.append(os.path.join(pathlib.Path().resolve(), "configs", host_site))



try:
    from wema_config import *

except ImportError:
    print(
        "Failed the wemaname approach to config file.\n"
        + str(host_site)
        + " isn't a real place, or there isn't a config file \
                        that I can find!"
    )

    try:
        if not sys.stdin.isatty():
            raise SystemExit(
                "No site config found. Set PTR_WEMA_SITE (e.g. PTR_WEMA_SITE=dev), "
                "add a wemaname* file, or run interactively."
            )
        site_name = input("What site am I running at?\n")
        sys.path.append(os.path.join(pathlib.Path().resolve(), "configs", site_name))
        from site_config import *

    except ImportError:
        print(
            str(site_name)
            + " isn't a real place, or there isn't a config file \
                        that I can find! Make sure you supplied \
                        a correct site name. Exiting."
        )
        sys.exit()
