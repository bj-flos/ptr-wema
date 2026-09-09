# -*- coding: utf-8 -*-
"""
Photon Ranch service endpoints for ptr-wema.

Each service is a separate deployment in production -- config is
photonranch-api, and status, jobs, calendar, logs and projects are their own
lambdas -- and their URLs used to be hardwired at every call site, which made it
impossible to run a site against anything else.  Each now has an env-overridable
root here, read from .env through python-dotenv before any endpoint is used.

The defaults are the local stack on loopback, NOT production: a misconfigured
run should fail rather than reach the live service.  The ports match the
per-service containers -- api 8091, status 8092, jobs 8093, calendar 8094,
projects 8095, logs 8090/logs -- see configs/dpo17/README.md for which repo
serves each, and ptr-site/sites/*.env, where a containerised site points the
same six roots at http://ptr-nginx:809x.

To reach LCO production, every root must be set explicitly:

    PTR_API_ROOT=https://api.photonranch.org/api
    PTR_STATUS_ROOT=https://status.photonranch.org/status
    PTR_JOBS_ROOT=https://jobs.photonranch.org/jobs
    PTR_CALENDAR_ROOT=https://calendar.photonranch.org/calendar
    PTR_LOGS_ROOT=https://logs.photonranch.org/logs
    PTR_PROJECTS_ROOT=https://projects.photonranch.org/projects

is_offbox() reports whether anything ended up off this machine.  Each root is
the part of the URL before the per-request path, and none of them carry a
trailing slash.
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
