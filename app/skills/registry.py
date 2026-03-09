from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from app.agent.models import PlannedSkillCall, PlannedToolCall


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    handler: Callable[..., list[PlannedToolCall]]


def build_skill_registry() -> dict[str, SkillDefinition]:
    return {
        "local_qa_skill": SkillDefinition(
            name="local_qa_skill",
            description="Answer local knowledge questions by searching indexed Notion pages and local files before generating a response.",
            handler=execute_local_qa_skill,
        ),
        "multi_source_research_skill": SkillDefinition(
            name="multi_source_research_skill",
            description="Handle multi-source research questions that may require searching local knowledge across Notion and local files.",
            handler=execute_multi_source_research_skill,
        ),
        "link_research_skill": SkillDefinition(
            name="link_research_skill",
            description="Handle saved-link questions, top domains, domain-level note analysis, and optional follow-up network reading.",
            handler=execute_link_research_skill,
        ),
        "memory_skill": SkillDefinition(
            name="memory_skill",
            description="Save or recall facts, preferences, and long-term memory relevant to the current session.",
            handler=execute_memory_skill,
        ),
        "recent_activity_skill": SkillDefinition(
            name="recent_activity_skill",
            description="List recently indexed pages and recent local knowledge activity.",
            handler=execute_recent_activity_skill,
        ),
        "generic_research_skill": SkillDefinition(
            name="generic_research_skill",
            description="Fallback skill that performs a generic local-first search when no specialized skill matches.",
            handler=execute_generic_research_skill,
        ),
    }


def serialize_skill_descriptions(registry: dict[str, SkillDefinition]) -> list[dict]:
    return [{"name": item.name, "description": item.description} for item in registry.values()]


def build_tool_calls_from_skills(
    registry: dict[str, SkillDefinition],
    planned_skills: list[PlannedSkillCall],
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    tool_calls: list[PlannedToolCall] = []
    for planned_skill in planned_skills:
        definition = registry.get(planned_skill.skill_name)
        if not definition:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="unknown_skill",
                    arguments={"skill_name": planned_skill.skill_name},
                    reason=f"Unknown skill: {planned_skill.skill_name}",
                    skill_name=planned_skill.skill_name,
                )
            )
            continue
        tool_calls.extend(
            definition.handler(
                planned_skill,
                question=question,
                top_k=top_k,
                observations=observations,
            )
        )
    return tool_calls


def execute_local_qa_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    if observations:
        return []
    return [
        PlannedToolCall(
            tool_name="search_local_notion",
            arguments={
                "query": str(skill.arguments.get("query", "")).strip() or question,
                "top_k": int(skill.arguments.get("top_k") or top_k),
            },
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def execute_multi_source_research_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    if observations:
        return []
    return [
        PlannedToolCall(
            tool_name="search_local_notion",
            arguments={
                "query": str(skill.arguments.get("query", "")).strip() or question,
                "top_k": int(skill.arguments.get("top_k") or max(top_k, 7)),
            },
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def execute_recent_activity_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    if observations:
        return []
    return [
        PlannedToolCall(
            tool_name="list_recent_pages",
            arguments={"limit": int(skill.arguments.get("limit") or 10)},
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def execute_memory_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    if observations:
        return []

    mode = str(skill.arguments.get("mode", "")).strip() or "lookup_memory"
    if mode == "save_preference":
        return [
            PlannedToolCall(
                tool_name="save_preference",
                arguments={
                    "category": str(skill.arguments.get("category", "")).strip() or "user_preference",
                    "content": str(skill.arguments.get("content", "")).strip() or question,
                    "confidence": float(skill.arguments.get("confidence") or 0.9),
                },
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    if mode == "save_memory":
        return [
            PlannedToolCall(
                tool_name="save_memory",
                arguments={
                    "content": str(skill.arguments.get("content", "")).strip() or extract_memory_content(question),
                    "importance": int(skill.arguments.get("importance") or 1),
                },
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    if mode == "lookup_preferences":
        return [
            PlannedToolCall(
                tool_name="lookup_preferences",
                arguments={
                    "query": str(skill.arguments.get("query", "")).strip() or question,
                    "limit": int(skill.arguments.get("limit") or 5),
                },
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    return [
        PlannedToolCall(
            tool_name="lookup_memory",
            arguments={
                "query": str(skill.arguments.get("query", "")).strip() or question,
                "limit": int(skill.arguments.get("limit") or 5),
            },
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def execute_link_research_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    mode = str(skill.arguments.get("mode", "")).strip() or "search_links"
    follow_up_read = bool(skill.arguments.get("follow_up_read"))
    if observations:
        if mode != "search_links" or not follow_up_read:
            return []
        last_observation = observations[-1]
        if last_observation.get("tool_name") != "search_saved_links":
            return []
        result = last_observation.get("result", [])
        if not isinstance(result, list) or not result:
            return []
        first_item = result[0] if isinstance(result[0], dict) else None
        if not first_item:
            return []
        links = first_item.get("links", [])
        if not links:
            return []
        return [
            PlannedToolCall(
                tool_name="read_network_link",
                arguments={"url": links[0], "max_chars": int(skill.arguments.get("max_chars") or 4000)},
                reason="Read the most relevant saved link after link retrieval.",
                skill_name=skill.skill_name,
            )
        ]

    if mode == "top_domains":
        return [
            PlannedToolCall(
                tool_name="list_top_link_domains",
                arguments={"limit": int(skill.arguments.get("limit") or 10)},
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    if mode == "pages_by_domain":
        return [
            PlannedToolCall(
                tool_name="find_pages_by_domain",
                arguments={
                    "domain": str(skill.arguments.get("domain", "")).strip() or extract_domain_candidate(question),
                    "limit": int(skill.arguments.get("limit") or 10),
                },
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    if mode == "domain_summary":
        return [
            PlannedToolCall(
                tool_name="get_link_domain_summary",
                arguments={"domain": str(skill.arguments.get("domain", "")).strip() or extract_domain_candidate(question)},
                reason=skill.reason,
                skill_name=skill.skill_name,
            )
        ]
    return [
        PlannedToolCall(
            tool_name="search_saved_links",
            arguments={
                "query": str(skill.arguments.get("query", "")).strip() or question,
                "limit": int(skill.arguments.get("limit") or 10),
                "follow_up_read": follow_up_read,
            },
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def execute_generic_research_skill(
    skill: PlannedSkillCall,
    *,
    question: str,
    top_k: int,
    observations: list[dict],
) -> list[PlannedToolCall]:
    if observations:
        return []
    return [
        PlannedToolCall(
            tool_name="search_local_notion",
            arguments={
                "query": str(skill.arguments.get("query", "")).strip() or question,
                "top_k": int(skill.arguments.get("top_k") or top_k),
            },
            reason=skill.reason,
            skill_name=skill.skill_name,
        )
    ]


def extract_memory_content(question: str) -> str:
    normalized = question.strip()
    prefixes = ("记住：", "记住:", "请记住：", "请记住:", "remember this:")
    for prefix in prefixes:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix):].strip() or normalized
    return normalized


def extract_domain_candidate(question: str) -> str:
    patterns = [
        r"(?:https?://)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?:/|$)",
        r"(github|notion|vercel|openai|react|vite|shadcn|recharts)\.(com|dev|io|org)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            if len(match.groups()) == 1:
                return match.group(1).lower()
            return ".".join(part for part in match.groups() if part).lower()
    lowered = question.lower()
    keyword_domains = {
        "github": "github.com",
        "notion": "notion.so",
        "openai": "openai.com",
        "vercel": "vercel.com",
        "shadcn": "ui.shadcn.com",
        "recharts": "recharts.org",
        "react": "react.dev",
    }
    for keyword, domain in keyword_domains.items():
        if keyword in lowered:
            return domain
    return ""
