from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator


class DailyBriefSchedule(BaseModel):
    schedule_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(default="每日简报", min_length=1, max_length=80)
    enabled: bool = False
    run_time: str = "08:00"
    timezone: str = "Asia/Shanghai"
    last_run_date: str = ""
    created_at: str = ""
    updated_at: str = ""

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, value: str) -> str:
        clean = value.strip()
        datetime.strptime(clean, "%H:%M")
        return clean

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("timezone cannot be empty")
        ZoneInfo(clean)
        return clean


class DailyBriefScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    run_time: str | None = None
    timezone: str | None = None

    @field_validator("run_time")
    @classmethod
    def validate_optional_run_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        datetime.strptime(clean, "%H:%M")
        return clean

    @field_validator("timezone")
    @classmethod
    def validate_optional_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("timezone cannot be empty")
        ZoneInfo(clean)
        return clean


class DailyBriefScheduleCreate(BaseModel):
    name: str = Field(default="每日简报", min_length=1, max_length=80)
    enabled: bool = True
    run_time: str = "08:00"
    timezone: str = "Asia/Shanghai"

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, value: str) -> str:
        clean = value.strip()
        datetime.strptime(clean, "%H:%M")
        return clean

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("timezone cannot be empty")
        ZoneInfo(clean)
        return clean
