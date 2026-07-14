from pathlib import Path

from pydantic import BaseModel, Field


class SkillRecord(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    enabled: bool = True
    source_path: Path
    body: str = ""
