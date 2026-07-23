from datetime import date

from pmaa.tools.calendar_tool import DisabledCalendarTool, LocalIcsCalendarTool


def test_disabled_calendar_returns_structured_unavailable_result() -> None:
    result = DisabledCalendarTool()({"date": "2026-07-23"})

    assert result["status"] == "unavailable"
    assert result["events"] == []
    assert result["date"] == "2026-07-23"


def test_local_ics_calendar_returns_only_target_day(tmp_path) -> None:
    calendar_path = tmp_path / "calendar.ics"
    calendar_path.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "BEGIN:VEVENT",
                "UID:event-1",
                "DTSTART:20260723T090000",
                "DTEND:20260723T100000",
                "SUMMARY:Project review",
                "LOCATION:Meeting room",
                "END:VEVENT",
                "BEGIN:VEVENT",
                "UID:event-2",
                "DTSTART:20260724T090000",
                "SUMMARY:Tomorrow event",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        ),
        encoding="utf-8",
    )

    result = LocalIcsCalendarTool(calendar_path)({"date": date(2026, 7, 23)})

    assert result["status"] == "ok"
    assert len(result["events"]) == 1
    assert result["events"][0]["title"] == "Project review"
