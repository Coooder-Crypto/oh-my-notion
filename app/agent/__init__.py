from __future__ import annotations


def answer_question(*args, **kwargs):
    from app.agent.service import answer_question as _answer_question

    return _answer_question(*args, **kwargs)


def answer_question_legacy(*args, **kwargs):
    from app.agent.service import answer_question_legacy as _answer_question_legacy

    return _answer_question_legacy(*args, **kwargs)

