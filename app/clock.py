"""The clock of the assistant: real Las Vegas time while the conference runs, a simulated time afterwards.

After the last session has finished the site keeps working as a simulation: the clock pretends it is a moment of the
event (default Monday 26 Oct 2026, 08:00), so search, "Can I make it?", the day planner and the walking routes behave
as they did live. A request can choose its own moment (simulateNow / simulate_now) without changing anything global.

EVENT_STATUS (environment): auto (default, ended after the last session), live, or ended.
SIMULATE_NOW (environment): the default simulated moment, for example 2026-10-26T08:00.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

EVENT_TZ = ZoneInfo("America/Los_Angeles")  # the event is in Las Vegas (PDT)
DEFAULT_SIMULATED = "2026-10-26T08:00"
_override: ContextVar[datetime | None] = ContextVar("simulated_now", default=None)


def real_now() -> datetime:
    """Current Las Vegas time (naive). Tests replace this function."""
    return datetime.now(EVENT_TZ).replace(tzinfo=None)


def parse_moment(text: Any) -> datetime | None:
    """'2026-10-27T10:30', '2026-10-27 10:30' or '2026-10-27' (then 08:00); None when it is not a moment."""
    if not text:
        return None
    t = str(text).strip().replace(" ", "T")
    try:
        d = datetime.fromisoformat(t if "T" in t else t + "T08:00")
    except ValueError:
        return None
    return d.replace(tzinfo=None)


def event_end() -> datetime | None:
    """The end of the last session in the catalog."""
    from .mcp_server import sessions  # local import: the catalog is loaded lazily

    ends = [datetime.fromisoformat(f"{s['date']}T{s['endTime']}") for s in sessions() if s.get("date") and s.get("endTime")]
    return max(ends) if ends else None


def event_ended() -> bool:
    status = os.environ.get("EVENT_STATUS", "auto").strip().lower()
    if status in ("live", "ended"):
        return status == "ended"
    end = event_end()
    return bool(end) and real_now() > end


def default_simulated() -> datetime:
    return parse_moment(os.environ.get("SIMULATE_NOW")) or parse_moment(DEFAULT_SIMULATED)


def now() -> datetime:
    """The moment the assistant works with: a request's own choice, else the simulated default once the event has
    ended, else the real time."""
    chosen = _override.get()
    if chosen:
        return chosen
    return default_simulated() if event_ended() else real_now()


def set_simulated(moment: Any) -> object | None:
    """Use this moment for the current request. Returns a token for reset_simulated(), or None when ignored."""
    d = parse_moment(moment)
    return _override.set(d) if d else None


def reset_simulated(token: object | None) -> None:
    if token is not None:
        _override.reset(token)  # type: ignore[arg-type]


def status() -> dict[str, Any]:
    """What every result and /health say about the state of the event."""
    ended = event_ended()
    out: dict[str, Any] = {"eventStatus": "ended" if ended else "live", "now": now().isoformat(timespec="minutes")}
    if ended:
        out["note"] = ("Oracle AI World 2026 has ended. Thank you for using the AI World Agenda Assistant! "
                       "The sessions can still be searched and planned as a simulation. We will be back next year.")
        out["simulation"] = True
    return out
