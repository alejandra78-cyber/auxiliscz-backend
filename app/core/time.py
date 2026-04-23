from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("America/La_Paz")


def local_now() -> datetime:
    """Current local datetime as timezone-aware."""
    return datetime.now(LOCAL_TZ)


def local_now_naive() -> datetime:
    """Current local datetime without timezone info for legacy timestamp columns."""
    return local_now().replace(tzinfo=None)

