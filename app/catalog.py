from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .venue import assess_transition


def load_catalog(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _blob(session: dict[str, Any]) -> str:
    fields: list[str] = []
    for k in ["code", "title", "description", "sessionType", "contentArea", "audienceLevel", "room", "area", "roomLocation"]:
        if session.get(k): fields.append(str(session[k]))
    for k in ["areasOfInterest", "industries", "jobRoles", "recommendationTopics"]:
        fields.extend(session.get(k) or [])
    return " ".join(fields).lower()


def session_matches(s: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("date") and s.get("date") != filters["date"]:
        return False
    if filters.get("from") and s.get("startTime") and s["startTime"] < filters["from"]:
        return False
    if filters.get("to") and s.get("endTime") and s["endTime"] > filters["to"]:
        return False
    if filters.get("room") and str(filters["room"]).lower() not in (s.get("roomLocation") or "").lower():
        return False
    if filters.get("level") not in (None, "") and str(s.get("level")) != str(filters["level"]):
        return False
    blob = _blob(s)
    for key in ["keyword", "contentArea", "areaOfInterest", "sessionType", "industry", "speaker", "company"]:
        val = filters.get(key)
        if val and str(val).lower() not in blob:
            return False
    return True


def search_sessions(sessions: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    q = (filters.get("query") or filters.get("keyword") or "").strip().lower()
    terms = [t for t in re.split(r"\W+", q) if len(t) > 1]
    out = []
    for s in sessions:
        if not session_matches(s, filters):
            continue
        if terms:
            blob = _blob(s)
            score = sum(3 if t in (s.get("title") or "").lower() else 1 for t in terms if t in blob)
            if score == 0:
                continue
        else:
            score = 0
        out.append((score, s))
    out.sort(key=lambda x: (-x[0], x[1].get("date") or "", x[1].get("startTime") or "", x[1].get("title") or ""))
    limit = int(filters.get("limit") or 50)
    return [s for _, s in out[: max(1, min(limit, 200))]]


def get_by_code(sessions: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    code = code.upper()
    return next((s for s in sessions if (s.get("code") or "").upper() == code), None)


def _minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def overlap(a: dict[str, Any], b: dict[str, Any], transition: int = 0) -> bool:
    if a.get("date") != b.get("date"):
        return False
    if not all([a.get("startTime"), a.get("endTime"), b.get("startTime"), b.get("endTime")]):
        return False
    return not (_minutes(a["endTime"]) + transition <= _minutes(b["startTime"]) or _minutes(b["endTime"]) + transition <= _minutes(a["startTime"]))


def find_conflicts(sessions: list[dict[str, Any]], codes: list[str], transition: int = 0) -> dict[str, Any]:
    selected = [get_by_code(sessions, c) for c in codes]
    selected = [s for s in selected if s]
    conflicts = []
    for i, a in enumerate(selected):
        for b in selected[i+1:]:
            if overlap(a, b, transition):
                conflicts.append({"a": a["code"], "b": b["code"], "reason": "overlap_or_transition"})
    travel = []
    for i, a in enumerate(selected):
        for b in selected[i+1:]:
            t = assess_transition(a, b)
            if t.get("gapMinutes") is not None and 0 <= t["gapMinutes"] <= 60:
                travel.append(t)
    missing = [c for c in codes if not get_by_code(sessions, c)]
    return {"sessions": selected, "conflicts": conflicts, "travel": travel, "missingCodes": missing}


def score_session(s: dict[str, Any], interests: list[str]) -> tuple[float, list[str]]:
    blob = _blob(s)
    title = (s.get("title") or "").lower()
    score = 0.0
    reasons: list[str] = []
    for interest in interests:
        term = interest.strip().lower()
        if not term:
            continue
        if term in title:
            score += 8
            reasons.append(f"Strong title match: {interest}")
        elif term in blob:
            score += 4
            reasons.append(f"Matches interest: {interest}")
    st = (s.get("sessionType") or "").lower()
    desc = (s.get("description") or "").lower()
    if any(x in desc for x in ["customer", "customers", "case study", "business outcomes", "lessons learned"]):
        score += 3
        reasons.append("Includes customer/business-outcome content")
    if "peer" in st or "panel" in title:
        score += 2
        reasons.append("Good peer/customer learning format")
    if any(x in blob for x in ["integration", "mcp", "agentic", "ai agents"]):
        score += 2
    return score, reasons


def optimize_agenda(sessions: list[dict[str, Any]], body: dict[str, Any]) -> dict[str, Any]:
    date = body.get("date")
    prefs = body.get("preferences") or {}
    interests = prefs.get("topics") or prefs.get("interests") or body.get("interests") or []
    transition = int(prefs.get("minimumTransitionMinutes") or body.get("minimumTransitionMinutes") or 10)
    fixed = body.get("fixedCommitments") or []

    candidates = [s for s in sessions if not date or s.get("date") == date]
    scored = []
    for s in candidates:
        score, reasons = score_session(s, interests)
        if score > 0:
            scored.append((score, reasons, s))
    scored.sort(key=lambda x: (-x[0], x[2].get("startTime") or ""))

    fixed_norm = []
    for c in fixed:
        fixed_norm.append({
            "code": None,
            "title": c.get("title", "Fixed commitment"),
            "date": c.get("date") or date,
            "startTime": c.get("startTime") or c.get("start"),
            "endTime": c.get("endTime") or c.get("end"),
            "fixed": True,
        })

    chosen: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    for score, reasons, s in scored:
        blocked = any(overlap(s, c, transition) for c in fixed_norm + [x["session"] for x in chosen])
        blocked = blocked or any(assess_transition(s, x["session"])["verdict"] == "unlikely" for x in chosen)
        item = {"session": s, "score": round(score, 2), "reasons": reasons}
        if blocked:
            if len(alternatives) < 20:
                alternatives.append(item)
        else:
            chosen.append(item)

    chosen.sort(key=lambda x: x["session"].get("startTime") or "")
    return {
        "date": date,
        "agenda": chosen,
        "fixedCommitments": fixed_norm,
        "alternatives": alternatives,
        "minimumTransitionMinutes": transition,
        "note": "Heuristic agenda. ChatGPT should apply conversational judgment, venue logistics, meal/networking needs, and user priorities before presenting a final schedule.",
    }
