from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo


class CalendarTool(Protocol):
    def __call__(self, request: dict[str, Any]) -> dict[str, Any]: ...


class DisabledCalendarTool:
    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "provider": "disabled",
            "date": str(request.get("date") or date.today().isoformat()),
            "events": [],
            "reason": "尚未配置日历数据源。",
        }


class LocalIcsCalendarTool:
    """Small read-only ICS connector. Recurring event expansion stays provider-side."""

    def __init__(self, path: str | Path, *, timezone: str = "Asia/Shanghai") -> None:
        self.path = Path(path)
        self.timezone = ZoneInfo(timezone)

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        target_date = self._target_date(request.get("date"))
        if not self.path.is_file():
            return {
                "status": "unavailable",
                "provider": "ics",
                "date": target_date.isoformat(),
                "events": [],
                "reason": f"ICS file not found: {self.path}",
            }
        events = [
            event
            for event in self._parse_events(self.path.read_text(encoding="utf-8-sig"))
            if event.get("date") == target_date.isoformat()
        ]
        return {
            "status": "ok",
            "provider": "ics",
            "date": target_date.isoformat(),
            "events": events,
        }

    def _parse_events(self, content: str) -> list[dict[str, Any]]:
        lines = self._unfold_lines(content)
        events: list[dict[str, Any]] = []
        current: dict[str, str] | None = None
        for line in lines:
            if line == "BEGIN:VEVENT":
                current = {}
                continue
            if line == "END:VEVENT":
                if current is not None:
                    event = self._event_from_fields(current)
                    if event is not None:
                        events.append(event)
                current = None
                continue
            if current is None or ":" not in line:
                continue
            raw_key, value = line.split(":", 1)
            key = raw_key.split(";", 1)[0]
            if key in {"DTSTART", "DTEND", "SUMMARY", "LOCATION", "DESCRIPTION", "UID"}:
                current[key] = value.strip()
        return events

    def _event_from_fields(self, fields: dict[str, str]) -> dict[str, Any] | None:
        raw_start = fields.get("DTSTART", "")
        if not raw_start:
            return None
        start = self._parse_datetime(raw_start)
        if start is None:
            return None
        raw_end = fields.get("DTEND", "")
        end = self._parse_datetime(raw_end) if raw_end else None
        all_day = len(raw_start) == 8 and raw_start.isdigit()
        return {
            "id": fields.get("UID", ""),
            "title": self._unescape(fields.get("SUMMARY", "未命名日程")),
            "date": start.date().isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat() if end else "",
            "all_day": all_day,
            "location": self._unescape(fields.get("LOCATION", "")),
            "description": self._unescape(fields.get("DESCRIPTION", "")),
        }

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            if len(value) == 8 and value.isdigit():
                parsed_date = datetime.strptime(value, "%Y%m%d").date()
                return datetime.combine(parsed_date, datetime.min.time(), self.timezone)
            if value.endswith("Z"):
                return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=ZoneInfo("UTC")
                ).astimezone(self.timezone)
            return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(
                tzinfo=self.timezone
            )
        except ValueError:
            return None

    @staticmethod
    def _target_date(value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                pass
        return date.today()

    @staticmethod
    def _unfold_lines(content: str) -> list[str]:
        lines: list[str] = []
        for raw_line in content.replace("\r\n", "\n").split("\n"):
            if raw_line.startswith((" ", "\t")) and lines:
                lines[-1] += raw_line[1:]
            else:
                lines.append(raw_line.strip())
        return lines

    @staticmethod
    def _unescape(value: str) -> str:
        return (
            value.replace("\\n", "\n")
            .replace("\\,", ",")
            .replace("\\;", ";")
            .replace("\\\\", "\\")
        )


CalendarToolFactory = Callable[[], CalendarTool]
