from __future__ import annotations

import json

from app.agent.models import PlannedSkillCall, PlannedToolCall
from app.core.config import Settings
from app.llm import create_openai_client
from app.skills.registry import (
    build_skill_registry,
    build_tool_calls_from_skills,
    extract_domain_candidate,
    extract_memory_content,
    serialize_skill_descriptions,
)


def plan_tool_calls(
    question: str,
    top_k: int = 5,
    settings: Settings | None = None,
    tool_descriptions: list[dict] | None = None,
    observations: list[dict] | None = None,
    session_history: list[dict] | None = None,
) -> list[PlannedToolCall]:
    skill_calls = plan_skill_calls(
        question=question,
        top_k=top_k,
        settings=settings,
        observations=observations,
        session_history=session_history,
    )
    return build_tool_calls_from_skills(
        build_skill_registry(),
        skill_calls,
        question=question,
        top_k=top_k,
        observations=observations or [],
    )


def plan_skill_calls(
    question: str,
    top_k: int = 5,
    settings: Settings | None = None,
    observations: list[dict] | None = None,
    session_history: list[dict] | None = None,
) -> list[PlannedSkillCall]:
    observation_items = observations or []
    skill_registry = build_skill_registry()
    if settings:
        llm_plan = plan_skill_calls_with_llm(
            question=question,
            settings=settings,
            skill_descriptions=serialize_skill_descriptions(skill_registry),
            observations=observation_items,
            session_history=session_history or [],
        )
        if llm_plan is not None:
            return normalize_planned_skills(llm_plan, question=question, top_k=top_k)

    normalized = question.strip().lower()
    wants_link_read = any(keyword in normalized for keyword in ("读取", "打开", "查看", "read", "open"))

    domain_candidate = extract_domain_candidate(question)

    if any(keyword in normalized for keyword in ("top domains", "top domain", "域名", "哪些网站保存最多", "链接最多的网站", "常见网站")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="link_research_skill",
                arguments={"mode": "top_domains", "limit": 10},
                reason="The user asks for domain-level link aggregation.",
            )
        ], question=question, top_k=top_k)

    if wants_link_read and any(keyword in normalized for keyword in ("链接", "link", "网址", "url", "文档", "官网", "website", "保存过")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="link_research_skill",
                arguments={"mode": "search_links", "query": question, "limit": 10, "follow_up_read": True},
                reason="The user wants to inspect a saved link, so link search should run before any network read.",
            )
        ], question=question, top_k=top_k)

    if domain_candidate and any(keyword in normalized for keyword in ("哪些笔记", "哪些页面", "保存过", "提到过", "出现过")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="link_research_skill",
                arguments={"mode": "pages_by_domain", "domain": domain_candidate, "limit": 10},
                reason="The user asks which pages mention a specific website/domain.",
            )
        ], question=question, top_k=top_k)

    if domain_candidate and any(keyword in normalized for keyword in ("总结", "summary", "概览", "这个网站", "该网站")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="link_research_skill",
                arguments={"mode": "domain_summary", "domain": domain_candidate},
                reason="The user asks for a summary of how a domain appears in the notes.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("链接", "link", "网址", "url", "文档", "官网", "website")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="link_research_skill",
                arguments={"mode": "search_links", "query": question, "limit": 10, "follow_up_read": False},
                reason="The user asks about saved links or online resources.",
            )
        ], question=question, top_k=top_k)

    if normalized.startswith(("我喜欢", "我偏好", "我更喜欢", "我通常")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="memory_skill",
                arguments={"mode": "save_preference", "category": "user_preference", "content": question, "confidence": 0.9},
                reason="The user states a stable preference that should be stored separately.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("之前", "刚才", "上次", "记忆", "memory", "remember")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="memory_skill",
                arguments={"mode": "lookup_memory", "query": question, "limit": 5},
                reason="The user refers to prior context or saved memory.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("记住", "remember this", "保存这个事实")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="memory_skill",
                arguments={"mode": "save_memory", "content": extract_memory_content(question), "importance": 2},
                reason="The user explicitly asks to remember something.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("偏好", "喜欢", "preference")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="memory_skill",
                arguments={"mode": "lookup_preferences", "query": question, "limit": 5},
                reason="The user asks about stable preferences or favored options.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("最近", "recent", "latest")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="recent_activity_skill",
                arguments={"limit": 10},
                reason="The user asks for recent pages.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("本地文件", "文件夹", "markdown", "txt", "pdf", "文档和 notion", "notion 和 文件", "文件和 notion")):
        return normalize_planned_skills([
            PlannedSkillCall(
                skill_name="multi_source_research_skill",
                arguments={"query": question, "top_k": max(top_k, 7)},
                reason="The user asks for an answer that may span local files and Notion content.",
            )
        ], question=question, top_k=top_k)

    return normalize_planned_skills([
        PlannedSkillCall(
            skill_name="local_qa_skill",
            arguments={"query": question, "top_k": top_k},
            reason="Default local-first retrieval for answering the question.",
        )
    ], question=question, top_k=top_k)


def plan_skill_calls_with_llm(
    question: str,
    settings: Settings,
    skill_descriptions: list[dict],
    observations: list[dict],
    session_history: list[dict],
) -> list[PlannedSkillCall] | None:
    client = create_openai_client(settings)
    if client is None:
        return None

    system_prompt = (
        "You are an agent planner for a local-first knowledge assistant. "
        "Return strict JSON only. "
        "Schema: {\"skill_calls\": [{\"skill_name\": string, \"arguments\": object, \"reason\": string}]}. "
        "If you already have enough information, return {\"skill_calls\": []}. "
        "Prefer local_qa_skill or multi_source_research_skill for knowledge questions. "
        "Use link_research_skill for links, docs, websites, URLs, official resources, or online references. "
        "Use memory_skill for remember, preference, or prior-context questions. "
        "Use recent_activity_skill for recent or latest pages."
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "skills": skill_descriptions,
            "observations": observations,
            "session_history": session_history,
        },
        ensure_ascii=False,
    )
    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        payload = json.loads(extract_json_object(response.output_text.strip()))
        calls = payload.get("skill_calls", [])
        planned_calls: list[PlannedSkillCall] = []
        for call in calls:
            skill_name = call.get("skill_name")
            arguments = call.get("arguments", {})
            reason = call.get("reason", "LLM selected this skill.")
            if not skill_name or not isinstance(arguments, dict):
                continue
            planned_calls.append(
                PlannedSkillCall(skill_name=skill_name, arguments=arguments, reason=reason)
            )
        return planned_calls
    except Exception:
        return None


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def normalize_planned_skills(
    calls: list[PlannedSkillCall],
    question: str,
    top_k: int,
) -> list[PlannedSkillCall]:
    normalized_calls: list[PlannedSkillCall] = []
    for call in calls:
        arguments = dict(call.arguments)
        if call.skill_name in {"local_qa_skill", "generic_research_skill"}:
            arguments["query"] = str(arguments.get("query", "")).strip() or question
            arguments["top_k"] = int(arguments.get("top_k") or top_k)
        elif call.skill_name == "multi_source_research_skill":
            arguments["query"] = str(arguments.get("query", "")).strip() or question
            arguments["top_k"] = int(arguments.get("top_k") or max(top_k, 7))
        elif call.skill_name == "link_research_skill":
            mode = str(arguments.get("mode", "")).strip() or "search_links"
            arguments["mode"] = mode
            if mode == "search_links":
                arguments["query"] = str(arguments.get("query", "")).strip() or question
                arguments["limit"] = int(arguments.get("limit") or 10)
                arguments["follow_up_read"] = bool(arguments.get("follow_up_read"))
            elif mode == "top_domains":
                arguments["limit"] = int(arguments.get("limit") or 10)
            else:
                arguments["domain"] = str(arguments.get("domain", "")).strip() or extract_domain_candidate(question)
                if mode == "pages_by_domain":
                    arguments["limit"] = int(arguments.get("limit") or 10)
        elif call.skill_name == "memory_skill":
            mode = str(arguments.get("mode", "")).strip() or "lookup_memory"
            arguments["mode"] = mode
            if mode == "save_memory":
                arguments["content"] = str(arguments.get("content", "")).strip() or extract_memory_content(question)
                arguments["importance"] = int(arguments.get("importance") or 1)
            elif mode == "save_preference":
                arguments["category"] = str(arguments.get("category", "")).strip() or "user_preference"
                arguments["content"] = str(arguments.get("content", "")).strip() or question
                arguments["confidence"] = float(arguments.get("confidence") or 0.9)
            else:
                arguments["query"] = str(arguments.get("query", "")).strip() or question
                arguments["limit"] = int(arguments.get("limit") or 5)
        elif call.skill_name == "recent_activity_skill":
            arguments["limit"] = int(arguments.get("limit") or 10)
        normalized_calls.append(
            PlannedSkillCall(
                skill_name=call.skill_name,
                arguments=arguments,
                reason=call.reason,
            )
        )
    return normalized_calls
