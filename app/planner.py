"""Strict day planner: no overlaps, a limit on how late you may arrive, plus lunch and networking blocks.

All walking times are estimates from data/venue.json. The planner maximises the total topic score
with dynamic programming over time-ordered nodes (sessions, a lunch block and networking blocks).
"""
from __future__ import annotations

import re
from typing import Any

from .catalog import has_started, score_session
from .venue import _label, _mins, late_minutes, session_zone, travel_minutes

LUNCH_BONUS = 1000.0
NETWORK_BONUS = 100.0
KEYNOTE_BONUS = 500.0
LUNCH_ZONE = "hall_g"
NETWORK_ZONE = "hub"
STEP = 5


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _topic_hit(s: dict[str, Any], topics: list[str]) -> bool:
    blob = " ".join(str(s.get(k) or "") for k in ("title", "description", "contentArea", "sessionType")).lower()
    blob += " " + " ".join(s.get("areasOfInterest") or []).lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(t.strip().lower()) + r"(?![a-z0-9])", blob) for t in topics if t.strip())


def _build_nodes(sessions, date, topics, include_hub_talks, include_keynote, lunch_minutes, lunch_window,
                 networking_blocks, networking_minutes, networking_window, d0, d1, fixed, hide_started=False):
    nodes: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for s in sessions:
        if s.get("date") != date or not (s.get("startTime") and s.get("endTime")):
            continue
        if hide_started and has_started(s):
            continue
        st = s.get("sessionType") or ""
        is_key = st == "Keynote"
        if st == "Activities" or (is_key and not include_keynote):
            continue
        zone = session_zone(s)
        if not zone or (zone == "hub" and not include_hub_talks):
            continue
        a, b = _mins(s["startTime"]), _mins(s["endTime"])
        if a < d0 or b > d1 or any(a < fe and fs < b for fs, fe, _ in fixed):
            continue
        if topics and not is_key and not _topic_hit(s, topics):
            continue
        score, _ = score_session(s, topics)
        node = {"kind": "session", "code": s["code"], "title": s["title"], "start": a, "end": b, "zone": zone,
                "value": KEYNOTE_BONUS if is_key else score * (b - a) / 45.0, "score": round(score, 2),
                "location": s.get("roomLocation") or s.get("room") or ""}
        candidates.append(node)
        nodes.append(node)
    if lunch_minutes > 0:
        for a in range(_mins(lunch_window[0]), _mins(lunch_window[1]) - lunch_minutes + 1, STEP):
            nodes.append({"kind": "lunch", "code": None, "title": "Lunch", "start": a, "end": a + lunch_minutes,
                          "zone": LUNCH_ZONE, "value": LUNCH_BONUS, "location": "Hall G, Level 1"})
    if networking_blocks > 0:
        for a in range(_mins(networking_window[0]), _mins(networking_window[1]) - networking_minutes + 1, 2 * STEP):
            nodes.append({"kind": "networking", "code": None, "title": "Networking", "start": a,
                          "end": a + networking_minutes, "zone": NETWORK_ZONE, "value": NETWORK_BONUS,
                          "location": "Oracle AI World Hub"})
    nodes.sort(key=lambda n: (n["start"], n["end"]))
    return nodes, candidates


def _best_chain(nodes, feasible, networking_blocks):
    """DP over time-ordered nodes. State = (networking blocks used, lunch used)."""
    best: list[dict[tuple[int, int], tuple[float, int | None, tuple[int, int] | None]]] = []
    for i, node in enumerate(nodes):
        dn = 1 if node["kind"] == "networking" else 0
        dl = 1 if node["kind"] == "lunch" else 0
        states: dict[tuple[int, int], tuple[float, int | None, tuple[int, int] | None]] = {}

        def offer(state, val, parent, pstate):
            if state[0] <= networking_blocks and state[1] <= 1 and (state not in states or val > states[state][0]):
                states[state] = (val, parent, pstate)

        offer((dn, dl), node["value"], None, None)
        for j in range(i):
            prev = nodes[j]
            if prev["end"] > node["start"] or (prev["kind"] == "networking" and node["kind"] == "networking"):
                continue
            if not feasible(prev, node):
                continue
            for ps, (pv, _, _) in best[j].items():
                offer((ps[0] + dn, ps[1] + dl), pv + node["value"], j, ps)
        best.append(states)
    top = None
    for i, states in enumerate(best):
        for st, (val, _, _) in states.items():
            if top is None or val > top[0]:
                top = (val, i, st)
    chain: list[dict[str, Any]] = []
    if top:
        i, st = top[1], top[2]
        while i is not None:
            chain.append(nodes[i])
            _, i, st = best[i][st]
        chain.reverse()
    return chain


def plan_day(
    sessions: list[dict[str, Any]],
    date: str,
    topics: list[str],
    late_tolerance_minutes: int = 2,
    lateness_basis: str = "worst",
    include_hub_talks: bool = True,
    include_keynote: bool = False,
    lunch_minutes: int = 30,
    lunch_window: tuple[str, str] = ("12:00", "14:00"),
    networking_blocks: int = 2,
    networking_minutes: int = 20,
    networking_window: tuple[str, str] = ("11:00", "18:00"),
    day_start: str = "08:00",
    day_end: str = "18:00",
    fixed_commitments: list[dict[str, str]] | None = None,
    dropped_limit: int = 10,
    hide_started: bool = False,
) -> dict[str, Any]:
    basis = "best" if lateness_basis == "best" else "worst"
    d0, d1 = _mins(day_start), _mins(day_end)
    fixed = [(_mins(c.get("startTime") or c["start"]), _mins(c.get("endTime") or c["end"]), c)
             for c in (fixed_commitments or [])]
    nodes, candidates = _build_nodes(sessions, date, topics, include_hub_talks, include_keynote, lunch_minutes,
                                     lunch_window, networking_blocks, networking_minutes, networking_window, d0, d1, fixed,
                                     hide_started)
    cache: dict[tuple[str, str, int], bool] = {}

    def feasible(a: dict[str, Any], b: dict[str, Any]) -> bool:
        gap = b["start"] - a["end"]
        if gap < 0:
            return False
        key = (a["zone"], b["zone"], gap)
        if key not in cache:
            lo, hi = travel_minutes(a["zone"], b["zone"])
            cache[key] = late_minutes(gap, lo, hi)[basis] <= late_tolerance_minutes
        return cache[key]

    chain = _best_chain(nodes, feasible, networking_blocks)

    schedule = []
    for n in chain:
        row = {"type": n["kind"], "code": n["code"], "title": n["title"], "startTime": _hhmm(n["start"]),
               "endTime": _hhmm(n["end"]), "location": n["location"]}
        if n["kind"] == "session":
            row["score"] = n["score"]
        schedule.append(row)

    moves = []
    for a, b in zip(chain, chain[1:]):
        gap = b["start"] - a["end"]
        lo, hi = travel_minutes(a["zone"], b["zone"])
        moves.append({"from": a["code"] or a["title"], "to": b["code"] or b["title"], "gapMinutes": gap,
                      "walkMinutes": {"best": lo, "worst": hi}, "lateIfWalking": late_minutes(gap, lo, hi),
                      "route": f"{_label(a['zone'])} -> {_label(b['zone'])}"})

    chosen = {n["code"] for n in chain if n["kind"] == "session"}
    dropped = []
    for c in sorted((c for c in candidates if c["code"] not in chosen), key=lambda x: -x["value"]):
        if len(dropped) >= dropped_limit:
            break
        clash = next((n for n in chain if c["start"] < n["end"] and n["start"] < c["end"]), None)
        if clash:
            reason = f"Overlaps {clash['code'] or clash['title']} ({_hhmm(clash['start'])}-{_hhmm(clash['end'])})"
        else:
            before = [n for n in chain if n["end"] <= c["start"]]
            after = [n for n in chain if n["start"] >= c["end"]]
            if before and not feasible(before[-1], c):
                reason = f"Too far from the previous stop ({before[-1]['code'] or before[-1]['title']})"
            elif after and not feasible(c, after[0]):
                reason = f"Too far to the next stop ({after[0]['code'] or after[0]['title']})"
            else:
                reason = "A higher-scoring combination was chosen"
        dropped.append({"code": c["code"], "title": c["title"], "startTime": _hhmm(c["start"]),
                        "endTime": _hhmm(c["end"]), "location": c["location"], "score": c["score"],
                        "reason": reason})

    warnings = []
    if lunch_minutes > 0 and not any(n["kind"] == "lunch" for n in chain):
        warnings.append("No lunch slot fits with the chosen sessions and lateness limit.")
    placed = sum(1 for n in chain if n["kind"] == "networking")
    if placed < networking_blocks:
        warnings.append(f"Only {placed} of {networking_blocks} networking blocks fit.")
    if any(n["zone"] == "hub" for n in chain):
        warnings.append("The Oracle AI World Hub is on Level 2, but its exact hall is unconfirmed, so Hub walking times are a range over Halls A-D.")
    return {
        "date": date,
        "rules": {"lateToleranceMinutes": late_tolerance_minutes, "latenessBasis": basis,
                  "includeHubTalks": include_hub_talks, "includeKeynote": include_keynote,
                  "lunchMinutes": lunch_minutes, "networkingBlocks": networking_blocks,
                  "networkingMinutes": networking_minutes, "networkingWindow": list(networking_window)},
        "schedule": schedule, "moves": moves, "dropped": dropped, "warnings": warnings,
        "note": "Walking times are rough estimates.",
    }
