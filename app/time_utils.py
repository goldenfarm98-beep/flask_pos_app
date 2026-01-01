import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - zoneinfo is standard in py3.9+
    ZoneInfo = None

_LOCAL_TZ = None


def _resolve_local_tz():
    global _LOCAL_TZ
    if _LOCAL_TZ is not None:
        return _LOCAL_TZ
    tz_name = os.environ.get("APP_TIMEZONE") or os.environ.get("TZ")
    if tz_name and ZoneInfo:
        try:
            _LOCAL_TZ = ZoneInfo(tz_name)
            return _LOCAL_TZ
        except Exception:
            _LOCAL_TZ = None
    _LOCAL_TZ = datetime.now().astimezone().tzinfo
    return _LOCAL_TZ


def local_now():
    tz = _resolve_local_tz()
    if tz:
        return datetime.now(tz).replace(tzinfo=None)
    return datetime.now()


def local_today():
    return local_now().date()
