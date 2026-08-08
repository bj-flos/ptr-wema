# -*- coding: utf-8 -*-
"""
Alpaca driver resolution for ptr-wema.

This module replaces the previous win32com (ASCOM COM) device layer so the
observatory code can run on Linux.  Devices are reached over ASCOM Alpaca
using the ``alpyca`` client library.

Site configs move from COM ProgIDs to Alpaca URLs:

    'ASCOM.QHYCCD.Camera'        ->  'alpaca://192.168.1.50:11111/camera/0'
    'ASCOM.PWI4.Telescope'       ->  'alpaca://192.168.1.50:11111/telescope/0'
    'ASCOM.OptecGemini.Focuser'  ->  'alpaca://192.168.1.50:11111/focuser/0'

alpyca exposes the ASCOM interface using the same PascalCase member names as
the old COM objects (``CameraXSize``, ``StartExposure``, ``Connected`` ...),
so the device call sites are unchanged apart from how the object is built.

The device number is optional and defaults to 0, and 'alpacas://' selects
https:

    'alpaca://host:11111/camera'     ->  device 0 over http
    'alpacas://host:11111/camera/1'  ->  device 1 over https
"""

from urllib.parse import urlparse

from alpaca.camera import Camera
from alpaca.covercalibrator import CoverCalibrator
from alpaca.dome import Dome
from alpaca.filterwheel import FilterWheel
from alpaca.focuser import Focuser
from alpaca.observingconditions import ObservingConditions
from alpaca.rotator import Rotator
from alpaca.safetymonitor import SafetyMonitor
from alpaca.switch import Switch
from alpaca.telescope import Telescope


DEVICE_CLASSES = {
    "camera": Camera,
    "covercalibrator": CoverCalibrator,
    "dome": Dome,
    "filterwheel": FilterWheel,
    "focuser": Focuser,
    "observingconditions": ObservingConditions,
    "rotator": Rotator,
    "safetymonitor": SafetyMonitor,
    "switch": Switch,
    "telescope": Telescope,
}

_ALPACA_SCHEMES = ("alpaca://", "alpacas://")

# ProgID prefixes that used to be handed to win32com.client.Dispatch.  They
# cannot work here, so name them explicitly rather than failing obscurely.
_COM_PREFIXES = ("ascom.", "maxim.", "ccdsoft", "thesky", "sky6", "pwi")


class DriverNotSupported(Exception):
    """Raised when a config asks for a driver this build cannot provide."""


def is_alpaca(driver):
    """Return True if ``driver`` is an Alpaca URL this module can dispatch."""
    return isinstance(driver, str) and driver.lower().startswith(_ALPACA_SCHEMES)


def parse_driver(driver):
    """Split an Alpaca URL into ``(address, device_type, device_number, protocol)``."""
    if not is_alpaca(driver):
        raise DriverNotSupported(
            "'%s' is not an Alpaca driver URL "
            "(expected 'alpaca://host:port/<devicetype>/<number>')." % (driver,)
        )

    parsed = urlparse(driver)
    protocol = "https" if parsed.scheme.lower() == "alpacas" else "http"

    address = parsed.netloc
    if not address:
        raise DriverNotSupported(
            "Alpaca driver '%s' does not specify a host:port." % (driver,)
        )

    parts = [segment for segment in parsed.path.split("/") if segment]
    if not parts:
        raise DriverNotSupported(
            "Alpaca driver '%s' does not name a device type." % (driver,)
        )

    device_type = parts[0].lower()
    if device_type not in DEVICE_CLASSES:
        raise DriverNotSupported(
            "Alpaca driver '%s' names unknown device type '%s'.  Known types: %s."
            % (driver, device_type, ", ".join(sorted(DEVICE_CLASSES)))
        )

    if len(parts) > 1:
        try:
            device_number = int(parts[1])
        except ValueError:
            raise DriverNotSupported(
                "Alpaca driver '%s' has a non-numeric device number '%s'."
                % (driver, parts[1])
            )
    else:
        device_number = 0

    return address, device_type, device_number, protocol


def dispatch(driver):
    """Return an alpyca device object for ``driver``.

    Drop-in replacement for ``win32com.client.Dispatch``.  The returned object
    is not yet connected; callers set ``.Connected = True`` exactly as they did
    with the COM object.
    """
    if not is_alpaca(driver):
        lowered = str(driver).lower()
        if lowered.startswith(_COM_PREFIXES):
            raise DriverNotSupported(
                "'%s' is an ASCOM COM driver.  This build speaks Alpaca only and "
                "cannot load COM drivers.  Replace it in the site config with an "
                "Alpaca URL, e.g. 'alpaca://host:11111/camera/0'." % (driver,)
            )
        raise DriverNotSupported(
            "'%s' is not an Alpaca driver URL "
            "(expected 'alpaca://host:port/<devicetype>/<number>')." % (driver,)
        )

    address, device_type, device_number, protocol = parse_driver(driver)
    return DEVICE_CLASSES[device_type](address, device_number, protocol=protocol)


def with_device_type(driver, device_type, device_number=None):
    """Return the same Alpaca URL aimed at a different device type.

    Replaces the COM-era string trick ``driver.replace('Rotator', 'Telescope')``,
    which relied on ProgIDs embedding the device type.  The device number is
    carried over unless one is given explicitly.
    """
    address, _, existing_number, protocol = parse_driver(driver)
    scheme = "alpacas" if protocol == "https" else "alpaca"
    number = existing_number if device_number is None else device_number
    return "%s://%s/%s/%d" % (scheme, address, device_type.lower(), number)


def CoInitialize():
    """No-op stand-in for ``win32com.client.pythoncom.CoInitialize()``.

    Alpaca is plain HTTP, so there is no COM apartment to initialise.  Kept as
    a named no-op so the device modules read the way they used to and so any
    remaining call sites stay harmless.
    """
    return None
