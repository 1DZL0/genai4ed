"""A stand-in class agent for running the platform with no model.

Used when no OpenRouter key is set: simple, predictable replies that still go
through every real part of the loop. It matches wording, not meaning.
"""

import json
import re

from app.agent import scaffold
from app.agent.brief import activity_guess, age_from_words
from app.agent.supervisor import normalise
from app.enums import ActivityKind

_WORDS = re.compile(r"\w+")

# The stub matches wording, not meaning: these are the plain attempts it will notice as a
# student trying to get the answer or set the rules aside. The real agent judges this itself.
_MANIPULATION = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore (all |your |the )?(previous |prior |earlier )?(instructions|rules|prompt)",
        r"\b(forget|disregard) (your|the|all) (rules|instructions)",
        r"\byou are now\b",
        r"\b(pretend|act as if) (you are|you're) (not|my|a) ",
        r"\bsystem prompt\b",
        r"\bjust (tell|give) me the (answer|solution)",
        r"\b(write|do) (it|this|the (essay|paragraph|homework|work|answer)) for me\b",
        r"\bmy teacher (said|says) (you can|it'?s ok|you're allowed)",
        r"\bdeveloper mode\b",
    )
]


def notices_manipulation(text: str) -> bool:
    """Whether the stub treats this message as an attempt to get the answer or break a rule."""
    return any(p.search(text or "") for p in _MANIPULATION)


def demo_responder(purpose: str, system: str, messages: list[dict]) -> dict:
    handler = {
        "teacher_thread": _teacher,
        "student_turn": _student,
        "lesson_review": _review,
    }.get(purpose)
    if handler is None:
        raise ValueError(f"The scripted agent can't do {purpose!r}.")
    return handler(system, messages)


def _json_after(system: str, marker: str) -> dict:
    """The JSON object that follows `marker` in the system prompt, or {}."""
    start = system.find(marker)
    if start == -1:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(system[start + len(marker) :].lstrip())
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _user_texts(messages: list[dict]) -> list[str]:
    """The words of every user message, oldest first."""
    texts = []
    for m in messages:
        if m["role"] == "user":
            content = m["content"]
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
            texts.append(str(content))
    return texts


# How a reply sent back for one more try is asked for again (llm.ask_structured): that message
# is the server's, so the words the stand-in answers are the ones before it.
_SENT_BACK = "Send the corrected JSON object only"


def _last_user_text(messages: list[dict]) -> str:
    texts = [t for t in _user_texts(messages) if _SENT_BACK not in t]
    return texts[-1] if texts else ""


# Words that say what the students will do, and the heading and kind the demo agent takes them
# for, the first that matches. The real agent judges this from meaning.
_DOING = [
    (re.compile(p, re.IGNORECASE), key, kind)
    for p, key, kind in (
        (r"\bessays?\b", "writing", "essay writing"),
        (r"\bletters?\b", "writing", "letter writing"),
        (r"\bstor(?:y|ies)\b", "writing", "creative writing"),
        (r"\bsummar", "writing", "summary writing"),
        (r"\bwrit(?:e|ing)\b", "writing", "paragraph writing"),
        (r"\bsolv", "maths", "multi-step problems"),
        (r"\bcalculat", "maths", "one-step problems"),
        (r"\bmultiple[- ]choice\b|\bquiz", "choice", "multiple choice"),
        (r"\bfill in\b|\bblanks\b", "choice", "fill-in-the-blanks"),
        (r"\bread (?:a|the)\b|\bpassage\b", "reading", "identifying main ideas"),
        (r"\bexperiment", "inquiry", "designing experiments"),
        (r"\bhypothes", "inquiry", "formulating hypotheses"),
        (r"\bbias\b", "critical", "identifying bias"),
        (r"\bevaluat", "critical", "evaluating claims and evidence"),
    )
]


def _doing(text: str) -> tuple[str, str] | None:
    """The heading and kind the teacher's words give, when they say what the students will do."""
    return next(((key, kind) for p, key, kind in _DOING if p.search(text)), None)


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
    """`rules` updated from the teacher's sentence, and whether anything changed."""
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


def _objectives(text: str, topic: str) -> list[str]:
    """The objective in the teacher's words, the sentence that says it; the demo agent's own
    two when their words give none, as the follow-up button's do."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if _OBJECTIVE.search(sentence):
            return [sentence.strip()[:300]]
    return [
        f"Explain the main idea of {topic} in their own words",
        f"Apply {topic} to a new example",
    ]


def _draft(brief: dict, text: str) -> dict:
    """The lesson as it should now be, after what the teacher just said."""
    lowered = text.lower()
    rules, rules_changed = _rules_from(text, dict(brief.get("rules") or {}))
    minutes = re.search(r"(\d+)\s*-?\s*min", lowered)

    if not brief.get("steps"):
        topic = _topic(text)
        prior = re.search(r"already (?:covered|did|done|know|learned|learnt) ([^.]+)", lowered)
        age = age_from_words(text)
        activity = activity_guess(text) or ActivityKind.ANSWERS
        # The heading and kind their words give, as a guess.
        heading, kind = _doing(text) or ("", "")
        brief = {
            "title": topic[:1].upper() + topic[1:],
            "subject": brief.get("subject") or _subject(text),
            "age": age,
            "activity": activity.value,
            "heading": heading,
            "listed_kind": kind,
            "to_check": ["the kind of activity"],
            "duration_minutes": int(minutes.group(1)) if minutes else None,
            "prior_knowledge": prior.group(1).strip() if prior else "",
            "objectives": _objectives(text, topic),
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
            "rules_text": text if rules_changed else "",
            "rules": rules,
            "topics": [topic.lower()[:40]],
        }
        named = f"I've called it '{brief['title']}'. Change it if you like. "
        guess = f"I'm guessing it is {kind}. Tell me if you meant something else. " if kind else ""
        questions = (("What age are the students?", age), ("How long is the lesson?", minutes))
        unknown = [q for q, said in questions if said is None]
        asks = " ".join(unknown[:2]) or "Should the agent ever give students the final answer?"
        length = f"{brief['duration_minutes']}-minute " if brief["duration_minutes"] else ""
        return {
            "reply": (
                f"(Demo agent, no AI model connected.) I've drafted a {length}"
                f"conversational activity on {topic} in four steps: recall, the big idea, "
                f"try it, and a check. {named}{guess}{asks}"
            ),
            "brief": brief,
            "open_questions": ["Is this the right level?", "When may the agent give answers?"],
            "gave": "part" if _doing(text) else "topic",
        }

    changes: list[str] = []
    if brief.get("age") is None and age_from_words(text) is not None:
        brief["age"] = age_from_words(text)
        changes.append(f"noted the students are {brief['age']}")
    if rules_changed:
        brief["rules"] = rules
        brief["rules_text"] = (brief.get("rules_text", "") + " " + text).strip()[:3000]
        changes.append("updated the rules for the agent")
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
    }


# ---------- the teacher's thread ----------

# How the demo agent opens a reply that asks before it drafts, as the real agent's does.
_ASK_FIRST = "Before I draft:"
# What a teacher's words say the students should be able to do by the end.
_OBJECTIVE = re.compile(
    r"\bby the end\b|\bbe able to\b|\bobjectives?\b|\bshould (learn|understand|know)\b",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"(\d+)\s*-?\s*min", re.IGNORECASE)


def _missing(text: str) -> list[str]:
    """What the teacher's words still lack of the three a lesson is drafted from, as the demo
    agent asks for it, the objective first."""
    asks = (
        ("What should they be able to do by the end?", _OBJECTIVE.search(text)),
        ("What age are the students?", age_from_words(text)),
        ("How long is the lesson, in minutes?", _MINUTES.search(text)),
    )
    return [question for question, given in asks if given is None]


def _said_since_asked(messages: list[dict]) -> tuple[list[str], bool]:
    """The teacher's words a lesson is drafted from, and whether they answer the demo agent's
    asking: their last message and, while the demo agent has been asking before it drafts, the
    messages it was asking about. A reply sent back for one more try, and the server's words
    sending it back, are left out."""
    said: list[str] = []
    answering = skip = False
    wanted = True  # a message of the teacher's is what comes next, going back
    for m in reversed(messages):
        content = m["content"] if isinstance(m["content"], str) else ""
        if m["role"] == "user":
            words = _user_texts([m])[0]
            skip = _SENT_BACK in words
            if skip:
                continue
            if not wanted:
                break
            said.insert(0, words)
            wanted = False
        elif skip:
            skip = False
        elif _ASK_FIRST in content:
            answering = wanted = True
        else:
            break
    return said or [""], answering


_CLASS_WORDS = ("class", "everyone", "they doing", "struggling", "who needs", "going", "board")
_OUTCOME_WORDS = ("outcome", "mark", "grade", "score", "result")
_LIST_WORDS = ("my lessons", "what lessons", "lessons do i", "which lessons")
# Words that mean the teacher is shaping a lesson, not asking about one running.
_DESIGN_WORDS = ("teach", "lesson on", "minute", "objective", "activity", "make it", "rule")
_ASKING = ("how", "who", "what", "which", "is ", "are ", "anyone", "show me", "show the")


def _teacher(system: str, messages: list[dict]) -> dict:
    """One turn of the teacher's thread: a reply, and which card to put up."""
    text = _last_user_text(messages)
    in_focus = "The lesson in focus is id " in system
    lowered = text.lower()
    klass = _json_after(system, "The class right now:\n")
    students = klass.get("students", [])
    asking = lowered.rstrip().endswith("?") or lowered.startswith(_ASKING)
    designing = any(w in lowered for w in _DESIGN_WORDS)

    for student in students:
        if student["pseudonym"].lower() in lowered:
            note = student.get("note") or f"on “{student.get('step', '')}”"
            state = student["state"].replace("_", " ")
            return {
                "reply": f"(Demo agent.) {student['pseudonym']} is {state}, {note}",
                "show": "student",
                "student_ref": student["pseudonym"],
            }

    if any(w in lowered for w in _OUTCOME_WORDS) and not designing:
        return {"reply": "(Demo agent.) Here is where the outcomes stand.", "show": "outcomes"}

    if students and asking and not designing and any(w in lowered for w in _CLASS_WORDS):
        struggling = [s["pseudonym"] for s in students if s["state"] in ("struggling", "needs_you")]
        reply = (
            f"(Demo agent.) Needing you now: {', '.join(struggling)}."
            if struggling
            else "(Demo agent.) Nobody is stuck at the moment."
        )
        return {"reply": reply, "show": "class"}

    if any(w in lowered for w in _LIST_WORDS):
        return {"reply": "(Demo agent.) These are your lessons.", "show": "lessons"}

    # A new lesson when nothing is in focus, the teacher says so, names another topic, or is
    # answering what the demo agent asked before it drafts.
    brief = _json_after(system, "The lesson in focus:\n")
    said, answering = _said_since_asked(messages)
    topic = _topic(text)
    fresh = (
        answering
        or not in_focus
        or "new lesson" in lowered
        or "another lesson" in lowered
        or (topic != "the topic" and topic.lower() not in (brief.get("title") or "").lower())
    )
    if fresh:
        # Asked first, as the real agent is: drafted once their words give an objective, the
        # age and the length. Words that ask outright for a draft, as the follow-up button's
        # do, are drafted as they stand.
        text = "\n".join(said)
        missing = _missing(text)
        if missing and not re.search(r"\bdraft\b", text, re.IGNORECASE):
            return {
                "reply": f"(Demo agent, no AI model connected.) {_ASK_FIRST} "
                + " ".join(missing[:2]),
                "show": "nothing",
                "gave": "topic",
            }
    # Drafted from their words alone, whatever they say of the kind of activity.
    drafted = _draft({} if fresh else brief, text)
    return {
        "reply": drafted["reply"],
        "show": "lesson",
        "brief": drafted["brief"],
        "new_lesson": fresh,
        "gave": drafted.get("gave", ""),
    }


# ---------- teaching a student ----------

# The few misconceptions the script can recognise by their wording.
_MISCONCEPTIONS = [
    (
        r"\b(food|glucose)\b.*\bsoil\b|\bsoil\b.*\b(food|feeds?)\b",
        "Thinks plants get their food from the soil",
        "Lots of people think that. Roots take in water and minerals, but that isn't food. "
        "If the food doesn't come from the soil, where could the plant be making it?",
    ),
]


def _student(system: str, messages: list[dict]) -> dict:
    situation = _json_after(system, scaffold.DATA_LABEL)
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

    if notices_manipulation(text):
        # The agent's own call on when the teacher should hear: the second time it happens.
        asked = sum(
            1 for m in messages if m["role"] == "user" and notices_manipulation(m["content"])
        )
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
                    "tell_teacher": asked >= 2,
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

    for pattern, misconception, challenge in _MISCONCEPTIONS:
        if re.search(pattern, lowered):
            return {
                "message": challenge,
                "move": "challenge",
                "student_attempted": True,
                "assessment": {
                    "judgment": "not_met",
                    "criterion": (step.get("success_criteria") or [""])[0],
                    "evidence_quote": text[:200],
                    "misconception": misconception,
                },
            }

    words = len(_WORDS.findall(text))
    reference = step.get("reference_answer") or ""
    if (reference and normalise(reference) in normalise(text)) or words >= 9:
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


def _review(system: str, messages: list[dict]) -> dict:
    snapshot = _json_after(system, "The lesson:\n")
    criteria = snapshot.get("criteria", [])
    outcomes = []
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
                "learns": ["(Demo agent.) Says more when asked to explain a step."],
            }
        )
    return {
        "summary": "(Demo agent.) Lesson summary based on step judgments.",
        "outcomes": outcomes,
    }
