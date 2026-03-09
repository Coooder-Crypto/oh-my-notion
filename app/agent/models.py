from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict
    reason: str
    skill_name: str = "unknown"


@dataclass(slots=True)
class PlannedSkillCall:
    skill_name: str
    arguments: dict
    reason: str
