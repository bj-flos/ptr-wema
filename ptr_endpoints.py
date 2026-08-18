# -*- coding: utf-8 -*-
"""
Photon Ranch service endpoints for ptr-wema.

These used to be hardwired to LCO's production hosts at every call site, which
made it impossible to run a site against anything else.  The defaults below are
exactly those production URLs, so behaviour is unchanged unless one of the
environment variables is set -- typically from .env, which is loaded here through
python-dotenv before importing this module.

To run against a local stand-in (see PTR/ptr-api-stub), set:

    PTR_API_ROOT=http://127.0.0.1:8091

Each root is the part of the URL before the per-request path, and none of them
carry a trailing slash.
"""

import os

try:
    # wema.py never calls load_dotenv itself, so do it here: this module is
    # imported before any endpoint is used.
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:      # python-dotenv is optional
    pass

PTR_API_ROOT = os.environ.get(
    "PTR_API_ROOT", "http://127.0.0.1:8091").rstrip("/")

PTR_STATUS_ROOT = os.environ.get(
    "PTR_STATUS_ROOT", "http://127.0.0.1:8092").rstrip("/")

PTR_JOBS_ROOT = os.environ.get(
    "PTR_JOBS_ROOT", "http://127.0.0.1:8093").rstrip("/")

PTR_CALENDAR_ROOT = os.environ.get(
    "PTR_CALENDAR_ROOT", "http://127.0.0.1:8094").rstrip("/")

PTR_LOGS_ROOT = os.environ.get(
    "PTR_LOGS_ROOT", "http://127.0.0.1:8090/logs").rstrip("/")

PTR_PROJECTS_ROOT = os.environ.get(
    "PTR_PROJECTS_ROOT", "http://127.0.0.1:8095").rstrip("/")


def is_offbox():
    """True if any endpoint points somewhere other than this machine.

    The defaults are all loopback, so this only fires when the environment has
    been pointed at a remote deployment -- worth logging loudly at startup.
    """
    roots = (PTR_API_ROOT, PTR_STATUS_ROOT, PTR_JOBS_ROOT,
             PTR_CALENDAR_ROOT, PTR_LOGS_ROOT, PTR_PROJECTS_ROOT)
    return not all("127.0.0.1" in r or "localhost" in r for r in roots)

def describe():
    """One-line-per-service summary, handy at startup."""
    return "\n".join([
        "  api      %s" % PTR_API_ROOT,
        "  status   %s" % PTR_STATUS_ROOT,
        "  jobs     %s" % PTR_JOBS_ROOT,
        "  logs     %s" % PTR_LOGS_ROOT,
        "  calendar %s" % PTR_CALENDAR_ROOT,
        "  projects %s" % PTR_PROJECTS_ROOT,
    ])
