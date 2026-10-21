from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

TITLE_CODE_RE = re.compile(r"^(.*?)\s*\[([A-Z]+\d+)\]\s*$")


def _text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _slug_values(classes: list[str], prefix: str) -> list[str]:
    return [c[len(prefix):] for c in classes if c.startswith(prefix)]


def _pretty_slug(slug: str) -> str:
    special = {
        "ai": "AI",
        "al": "AI",  # RainFocus snapshot uses al-agents in some CSS classes.
        "oci": "OCI",
        "erp": "ERP",
        "hcm": "HCM",
        "epm": "EPM",
        "cx": "CX",
        "api": "API",
        "saas": "SaaS",
        "iaas": "IaaS",
        "paas": "PaaS",
        "rpa": "RPA",
    }
    words = []
    for w in slug.split("-"):
        words.append(special.get(w, w.capitalize()))
    text = " ".join(words)
    text = text.replace("AI Agents", "AI Agents")
    return text


def _parse_date(date_text: str) -> str | None:
    # Example: Monday, Oct 26 -> 2026-10-26
    try:
        d = datetime.strptime(f"{date_text.strip()}, 2026", "%A, %b %d, %Y")
        return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
    except Exception:
        return None


def _parse_time_range(time_text: str) -> tuple[str | None, str | None, str | None]:
    # Example: 11:30 AM - 12:15 PM PDT
    m = re.match(r"\s*(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)\s*([A-Z]{2,5})?\s*$", time_text)
    if not m:
        return None, None, None
    def cvt(t: str) -> str:
        return datetime.strptime(t.replace(" ", ""), "%I:%M%p").strftime("%H:%M")
    return cvt(m.group(1)), cvt(m.group(2)), m.group(3) or None


@dataclass
class TileContext:
    element_id: str | None
    classes: list[str]
    depth: int = 1
    title_parts: list[str] = field(default_factory=list)
    date_parts: list[str] = field(default_factory=list)
    time_parts: list[str] = field(default_factory=list)
    description_parts: list[str] = field(default_factory=list)
    capture_title: int = 0
    capture_date: int = 0
    capture_time: int = 0
    capture_desc: int = 0


class CatalogHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: TileContext | None = None
        self.sessions: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        classes = (attrs_d.get("class") or "").split()

        if self.current is None:
            if tag == "div" and attrs_d.get("data-test") == "rf-tile" and "rf-tile-wrapper" in classes:
                self.current = TileContext(attrs_d.get("id"), classes)
            return

        if tag == "div":
            self.current.depth += 1

        # Captures are depth counters so nested tags remain included.
        if "rf-tile-title" in classes:
            self.current.capture_title = 1
        elif "session-date" in classes:
            self.current.capture_date = 1
        elif "session-time" in classes:
            self.current.capture_time = 1
        elif "rf-tile-line-two" in classes:
            self.current.capture_desc = 1
        else:
            if self.current.capture_title:
                self.current.capture_title += 1
            if self.current.capture_date:
                self.current.capture_date += 1
            if self.current.capture_time:
                self.current.capture_time += 1
            if self.current.capture_desc:
                self.current.capture_desc += 1

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return

        for name in ("capture_title", "capture_date", "capture_time", "capture_desc"):
            val = getattr(self.current, name)
            if val:
                setattr(self.current, name, val - 1)

        if tag == "div":
            self.current.depth -= 1
            if self.current.depth == 0:
                self.sessions.append(self._finalize(self.current))
                self.current = None

    def handle_data(self, data: str) -> None:
        if self.current is None or not data.strip():
            return
        if self.current.capture_title:
            self.current.title_parts.append(data)
        if self.current.capture_date:
            self.current.date_parts.append(data)
        if self.current.capture_time:
            self.current.time_parts.append(data)
        if self.current.capture_desc:
            self.current.description_parts.append(data)

    def _finalize(self, tile: TileContext) -> dict[str, Any]:
        title_raw = html.unescape(_text(tile.title_parts))
        code = None
        title = title_raw
        m = TITLE_CODE_RE.match(title_raw)
        if m:
            title, code = m.group(1).strip(), m.group(2)
        date_label = _text(tile.date_parts)
        time_label = _text(tile.time_parts)
        start, end, tz = _parse_time_range(time_label)

        def disp(prefix: str) -> list[str]:
            return [_pretty_slug(v) for v in _slug_values(tile.classes, prefix)]

        session_types = disp("session-type-")
        content_areas = disp("content-area-")
        audience = disp("audience-level-")

        return {
            "id": tile.element_id or code or title_raw,
            "externalId": (tile.element_id or "").removeprefix("session-") or None,
            "code": code,
            "title": title,
            "description": html.unescape(_text(tile.description_parts)),
            "date": _parse_date(date_label),
            "dateLabel": date_label,
            "startTime": start,
            "endTime": end,
            "timezone": tz,
            "sessionType": session_types[0] if session_types else None,
            "contentArea": content_areas[0] if content_areas else None,
            "areasOfInterest": disp("area-of-interest-"),
            "industries": disp("industry-"),
            "audienceLevel": audience[0] if audience else None,
            "jobRoles": disp("job-role-"),
            "deliveryTypes": disp("session-delivery-"),
            "recommendationTopics": disp("recommendations-topics-"),
            "notes": disp("note-"),
            "rawClasses": tile.classes,
        }


def parse_catalog_html(path: str | Path) -> list[dict[str, Any]]:
    parser = CatalogHTMLParser()
    # Read the whole file: feeding it in chunks lost a session whose tile straddled a chunk boundary.
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    parser.close()
    # Keep only actual sessions; malformed/navigation tiles have no title/date.
    return [s for s in parser.sessions if s.get("title") and s.get("date")]


def write_sessions_json(source_html: str | Path, output_json: str | Path) -> dict[str, Any]:
    source_html = Path(source_html)
    sessions = parse_catalog_html(source_html)
    payload = {
        "catalog": {
            "name": "Oracle AI World 2026 Session Catalog",
            "sourceUrl": "https://reg.rf.oracle.com/flow/oracle/oaiw26/catalog/page/catalog",
            "snapshotFile": source_html.name,
            "importedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sessionCount": len(sessions),
            "warning": "Snapshot data only. Verify time/location/availability in the official Oracle catalog before relying on it.",
        },
        "sessions": sessions,
    }
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Parse a saved Oracle AI World session catalog HTML snapshot.")
    p.add_argument("html")
    p.add_argument("--out", default="data/sessions.json")
    args = p.parse_args()
    payload = write_sessions_json(args.html, args.out)
    print(f"Parsed {payload['catalog']['sessionCount']} sessions -> {args.out}")
