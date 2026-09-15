"""A stand-in class agent for running the platform with no model.

Used when no OpenRouter key is set, so a demo still goes through every real
part of the loop - context, rules, checks, triage, evidence - with simple,
predictable replies. It is not meant to teach well; it is meant to be honest
about being a script (replies say so where it matters) and to exercise the
pipeline end to end.
"""

import json
import re

from app.agent.supervisor import normalise, screen_student_message

_WORDS = re.compile(r"\w+")


def demo_responder(purpose: str, system: str, messages: list[dict]) -> dict:
    handler = {
        "lesson_design": _design,
        "student_turn": _student,
        "class_answer": _class_answer,
        "class_insight": _class_insight,
        "lesson_review": _review,
    }.get(purpose)
    if handler is None:
        raise ValueError(f"The scripted agent can't do {purpose!r}.")
    return handler(system, messages)


def _json_after(system: str, marker: str) -> dict:
    start = system.find(marker)
    if start == -1:
        return {}
    text = system[start + len(marker) :]
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(text.lstrip())
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] == "user":
            content = m["content"]
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
            return str(content)
    return ""


# ---------- designing a lesson ----------


def _topic(text: str) -> str:
    for pattern in (
        r"\babout ([^.,;!?]+?)(?:\.|,|;|!|\?| they| for| to | in \d|$)",
        r"\bteach(?:ing)? (?:this class |them |my class )?([^.,;!?]+?)(?:\.|,|;| to | for|$)",
        r"\bon ([^.,;!?]+?)(?:\.|,|;|$)",
    ):
        found = re.search(pattern, text, re.IGNORECASE)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return "the topic"


_SUBJECTS = {
    "science": ("photosynth", "cell", "biolog", "chemi", "physic", "energy", "force", "atom"),
    "mathematics": ("equation", "algebra", "fraction", "geometry", "maths", "math"),
    "english": ("paragraph", "essay", "poem", "novel", "english", "writing"),
    "history": ("war", "history", "empire", "revolution"),
    "geography": ("river", "climate", "geography", "volcano"),
}


def _subject(text: str) -> str:
    lowered = text.lower()
    return next((s for s, words in _SUBJECTS.items() if any(w in lowered for w in words)), "")


def _rules_from(text: str, rules: dict) -> tuple[dict, bool]:
    lowered = text.lower()
    changed = False
    if "no hint" in lowered:
        rules["hints_allowed"] = False
        changed = True
    elif "hint" in lowered:
        rules["hints_allowed"] = True
        changed = True
    attempts = re.search(
        r"(?:attempted|tried|attempts?)\D{0,20}?(\d+|once|twice|three times)", lowered
    )
    if "final answer" in lowered or "the answer" in lowered:
        if attempts:
            word = attempts.group(1)
            count = {"once": 1, "twice": 2, "three times": 3}.get(word) or int(word)
            rules["full_answer_after_attempts"] = count
        elif "never" in lowered or "not" in lowered or "don't" in lowered:
            rules["full_answer_after_attempts"] = None
        changed = True
    if re.search(r"\b(flag|report|tell me|alert)\b", lowered):
        escalations = [
            e for e in rules.get("escalations", []) if e["signal"] != "manipulation_attempt"
        ]
        if re.search(r"complete|do (the|their) (work|assignment)|answers?|cheat", lowered):
            after = 2 if re.search(r"repeated|keeps|again|more than once", lowered) else 1
            escalations.append(
                {"signal": "manipulation_attempt", "after": after, "action": "alert"}
            )
            changed = True
        if "struggl" in lowered:
            escalations.append({"signal": "struggling", "after": 2, "action": "alert"})
            changed = True
        rules["escalations"] = escalations
    return rules, changed


def _design(system: str, messages: list[dict]) -> dict:
    brief = _json_after(system, "The brief so far:\n")
    text = _last_user_text(messages)
    lowered = text.lower()

    if not brief.get("steps"):
        topic = _topic(text)
        minutes = re.search(r"(\d+)\s*-?\s*min", lowered)
        prior = re.search(r"already (?:covered|did|done|know|learned|learnt) ([^.]+)", lowered)
        rules, _ = _rules_from(text, dict(brief.get("rules") or {}))
        brief = {
            "title": topic[:1].upper() + topic[1:],
            "subject": brief.get("subject") or _subject(text),
            "year_group": "",
            "duration_minutes": int(minutes.group(1)) if minutes else 30,
            "prior_knowledge": prior.group(1).strip() if prior else "",
            "objectives": [
                f"Explain the main idea of {topic} in their own words",
                f"Apply {topic} to a new example",
            ],
            "strategy": (
                "Start from what students already know, build the idea through questions, "
                "then check understanding with a short task."
            ),
            "steps": [
                {
                    "name": "What do you already know?",
                    "kind": "question",
                    "goal": f"Find out what the student already knows that connects to {topic}.",
                    "prompt_ideas": [f"What do you already know that might help with {topic}?"],
                    "success_criteria": ["Recalls at least one relevant idea"],
                },
                {
                    "name": "The big idea",
                    "kind": "explain",
                    "goal": f"Build the key idea of {topic} through explanation and questions.",
                    "prompt_ideas": [f"In your own words, what is {topic}?"],
                    "success_criteria": [f"Describes {topic} accurately in their own words"],
                },
                {
                    "name": "Try it",
                    "kind": "practice",
                    "goal": f"Use {topic} to explain an example.",
                    "prompt_ideas": [f"Here's a situation: how does {topic} explain it?"],
                    "success_criteria": ["Links the example to the idea with a reason"],
                },
                {
                    "name": "Check",
                    "kind": "check",
                    "goal": "Show understanding without help.",
                    "prompt_ideas": [f"Explain {topic} to someone who missed the lesson."],
                    "success_criteria": ["Accurate, complete, uses the key words"],
                },
            ],
            "assessment": [
                {"name": "Understanding", "max": 4, "description": "Accurate explanation"},
                {"name": "Reasoning", "max": 3, "description": "Gives reasons and examples"},
            ],
            "rules_text": text if _rules_from(text, {})[1] else "",
            "rules": rules,
            "topics": [topic.lower()[:40]],
        }
        return {
            "reply": (
                f"(Demo agent, no AI model connected.) I've drafted a {brief['duration_minutes']}-"
                f"minute conversational activity on {topic} in four steps: recall, the big idea, "
                "try it, and a check. Is this the right level for the class, and should the agent "
                "ever give students the final answer?"
            ),
            "brief": brief,
            "open_questions": ["Is this the right level?", "When may the agent give answers?"],
        }

    rules, rules_changed = _rules_from(text, dict(brief.get("rules") or {}))
    changes: list[str] = []
    if rules_changed:
        brief["rules"] = rules
        brief["rules_text"] = (brief.get("rules_text", "") + " " + text).strip()[:3000]
        changes.append("updated the rules for the agent")
    minutes = re.search(r"(\d+)\s*-?\s*min", lowered)
    if minutes:
        brief["duration_minutes"] = int(minutes.group(1))
        changes.append(f"set the length to {minutes.group(1)} minutes")
    if "harder" in lowered or "challeng" in lowered:
        brief["strategy"] = (
            brief.get("strategy", "") + " Push for reasons and harder cases."
        ).strip()
        changes.append("made it more challenging")
    if "easier" in lowered or "simpler" in lowered:
        brief["strategy"] = (
            brief.get("strategy", "") + " Keep language simple; more examples."
        ).strip()
        changes.append("made it more accessible")
    if not changes:
        brief["strategy"] = (brief.get("strategy", "") + f" Teacher note: {text}").strip()[:2000]
        changes.append("added your note to how the agent should teach")
    return {
        "reply": f"(Demo agent.) I've {', and '.join(changes)}. Anything else before approving?",
        "brief": brief,
        "open_questions": [],
    }


# ---------- teaching a student ----------


def _student(system: str, messages: list[dict]) -> dict:
    situation = _json_after(system, "The lesson and where this student is:\n")
    brief = situation.get("lesson_brief", {})
    where = situation.get("where_the_student_is", {})
    steps = brief.get("steps", [])
    index = int(where.get("step_number", 1)) - 1
    step = where.get("step") or (steps[index] if 0 <= index < len(steps) else {})
    attempts = int(where.get("answers_on_this_step", 0))
    ask = (step.get("prompt_ideas") or [step.get("goal", "Tell me what you think.")])[0]

    if situation.get("now"):
        return {
            "message": f"Hi! Today: {brief.get('title', 'our lesson')}. Let's start. {ask}",
            "move": "ask",
            "task": ask,
        }

    text = _last_user_text(messages)
    lowered = text.lower()
    button = (situation.get("student_used_button") or "").lower()

    if screen_student_message(text):
        return {
            "message": (
                "I can't hand over the answer, but I can help you get there. "
                f"What's your first thought about this: {ask}"
            ),
            "move": "decline",
            "signals": [
                {
                    "kind": "manipulation_attempt",
                    "severity": "medium",
                    "note": "Asked for the answer instead of trying.",
                }
            ],
        }
    if "understand" in button or "another way" in button or "don't understand" in lowered:
        return {
            "message": f"Let's look at it differently. The aim here is: {step.get('goal', '')} "
            f"Try again in your own words: {ask}",
            "move": "explain",
        }
    if "example" in button or "example" in lowered:
        return {
            "message": f"Here's a way in: think of an everyday case of this, then say how it "
            f"connects. {ask}",
            "move": "example",
        }
    if "wrong" in button:
        criteria = step.get("success_criteria") or ["give a reason"]
        return {
            "message": f"Your answer doesn't yet {criteria[0].lower()}. What could you add?",
            "move": "hint",
            "disclosure": "hint",
        }

    words = len(_WORDS.findall(text))
    reference = step.get("reference_answer") or ""
    if reference and normalise(reference) in normalise(text):
        judgment = "met"
    elif words >= 12:
        judgment = "met"
    elif words >= 5:
        judgment = "partial"
    else:
        judgment = "not_met"
    assessment = {
        "judgment": judgment,
        "criterion": (step.get("success_criteria") or [""])[0],
        "evidence_quote": text[:200],
    }

    if judgment == "met":
        if index + 1 >= len(steps):
            return {
                "message": "That's it - you've finished the activity. Well done!",
                "move": "complete",
                "student_attempted": True,
                "assessment": assessment,
                "signals": [{"kind": "fast_progress", "note": "Finished all steps."}]
                if attempts == 0
                else [],
            }
        nxt = steps[index + 1]
        next_ask = (nxt.get("prompt_ideas") or [nxt.get("goal", "")])[0]
        return {
            "message": f"Good - that works. Next: {nxt.get('name', '')}. {next_ask}",
            "move": "advance",
            "student_attempted": True,
            "assessment": assessment,
            "task": next_ask,
        }
    if judgment == "partial":
        return {
            "message": "You're on the right track. Can you say why, with a bit more detail?",
            "move": "justify",
            "student_attempted": True,
            "assessment": assessment,
        }
    signals = []
    if attempts >= 2:
        signals.append(
            {
                "kind": "struggling",
                "severity": "medium",
                "note": "Several short answers on this step.",
            }
        )
    return {
        "message": "Not quite yet. Here's a hint: think about what the question is really asking, "
        "and try a full sentence.",
        "move": "hint",
        "student_attempted": True,
        "assessment": assessment,
        "disclosure": "hint",
        "signals": signals,
    }


# ---------- the teacher's view of a lesson ----------


def _class_answer(system: str, messages: list[dict]) -> dict:
    snapshot = _json_after(system, "The class right now:\n")
    struggling = [
        s["pseudonym"] for s in snapshot.get("students", []) if s.get("state") == "struggling"
    ]
    question = _last_user_text(messages)
    if struggling:
        reply = f"(Demo agent.) Struggling right now: {', '.join(struggling)}."
    else:
        reply = "(Demo agent.) Nobody is flagged as struggling at the moment."
    return {"reply": reply + f" You asked: “{question[:120]}”.", "cited_students": struggling}


def _class_insight(system: str, messages: list[dict]) -> dict:
    snapshot = _json_after(system, "The class right now:\n")
    students = snapshot.get("students", [])
    finished = sum(1 for s in students if s.get("state") == "finished")
    patterns = snapshot.get("patterns", [])
    items = [{"text": f"{finished} of {len(students)} students have finished.", "students": []}]
    for p in patterns[:3]:
        items.append(
            {"text": f"Common misconception: {p['note']}", "students": p.get("students", [])}
        )
    return {"summary": "(Demo agent.) " + items[0]["text"], "items": items}


def _review(system: str, messages: list[dict]) -> dict:
    snapshot = _json_after(system, "The lesson:\n")
    outcomes = []
    criteria = snapshot.get("criteria", [])
    for s in snapshot.get("students", []):
        met = s.get("steps_met", 0)
        total = max(1, s.get("step_count", 1))
        outcomes.append(
            {
                "student_id": s["student_id"],
                "criteria": [
                    {
                        "name": c["name"],
                        "points": round(c["max"] * met / total),
                        "reason": f"{met} of {total} steps met.",
                    }
                    for c in criteria
                ],
                "keep": "Kept going through the activity.",
                "develop": ["Explain reasons in full sentences."],
            }
        )
    return {
        "summary": "(Demo agent.) Lesson summary based on step judgments.",
        "outcomes": outcomes,
    }
