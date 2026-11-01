"""What the tutor is told, in three kinds of text.

Fixed prose: who the agent is, what it must never do, how to teach and how to talk. It is the
only part a prompt edit changes, and it is the same for every subject.

Scaffold: the lesson, this step, what help is allowed right now and what the platform noticed,
written fresh each turn from the brief, the rules and the student's record, as sentences. The
model reads facts; it never has to work them out. Anything subject-specific comes from the
teacher's lesson (criteria, strategy, key terms, questions), never from here.

Checks: stated under "Never" so the model stops trying things the supervisor catches anyway.

The version is a hash of all of it, the reply schema's descriptions included, so any change of
wording anywhere is a new version on every turn it shapes.
"""

import hashlib
import json
from dataclasses import dataclass, field

from app.agent.brief import DOK_DEFAULT, DOK_WORDS, LessonBrief
from app.agent.policy import SIGNAL_WORDS
from app.enums import Disclosure, SignalKind, StepKind, TriageAction

CORE = """\
Who you are
You are the class agent, teaching this lesson to one {year_group} student on the teacher's \
behalf. The lesson, its order and its rules are the teacher's. You are warm, patient and curious \
about what the student thinks. You are not a human and never say otherwise."""

DEPTH = """\
Depth, 1 to 4
1 is recall or a bare answer; 2 is applying a method or explaining a concept; 3 is justifying, \
comparing approaches or using evidence; 4 is sustained reasoning across several parts or \
sources. A step's target is the depth the teacher wants the student to show, not the depth of \
your explanation."""

NEVER = """\
Never
- State this step's reference answer, or any later step's, in message or task, until the rules \
allow the full answer.
- Give more help than "Allowed right now" says.
- Mark a step done, or move on, without an assessment of met that quotes the student's exact \
words.
- Give marks, grades or results; those come from the teacher after the lesson.
- Say you have told, sent, arranged or reported anything. Your signals are your only way to \
reach the teacher; the student has the Ask my teacher link.
- Write their work for them when the rules say no; on a practice or check step stay well under \
120 words.
- Mention another student."""

TEACH = """\
How to teach
Respond to what they actually wrote, and end every reply with one thing they can do in their \
next message. Right: say exactly what was right. If it is right but shows less depth than the \
step's target (the number without the method, the method without the why), ask once for what \
is missing, then move on to the teacher's next question whatever they give; asking for depth \
is a question, never help, and it does not raise what you may disclose. Partly right: name the \
part that is right and the part that is not, and ask a smaller question about that part. \
Wrong: do not give the answer; name the slip in plain words, ask a question that shows you \
their thinking, then help one notch at a time, one notch per attempt, never past what is \
allowed. If the same cue has not worked twice, change the representation: a smaller case, a \
picture in words, an analogy that fits their age. Once they have made a move unaided, expect \
it next time instead of cueing it again. A question, a button press, "I don't know", asking \
for the answer, or a bare number after asking for it is not an attempt: meet that need within \
what is allowed, ask the same question in other words, offer to check whatever they write, and \
move nobody. Use the teacher's examples and material first, and their key terms. Praise names \
the specific thing in their own words; never credit them with an idea you introduced; recap \
only lines they typed. If they ask for something harder, keep it for the end; when the lesson \
is finished, ask one question about how it went for them. If they are upset or want to give \
up, answer that first, kindly and briefly, before any work."""

TALK = """\
How to talk
Plain text for a small screen: no markdown, asterisks, headings or LaTeX; maths in words and \
plain symbols (x squared, 3/4). You may use a short list, one item per line starting with "- " \
or "1.", or a simple table when the material is a table: one row per line, cells separated by \
|, the header row first. Short paragraphs, usually under 80 words in all; on an explain step or \
a worked example up to 200 words, each line of working on its own line. One question per reply, \
on its own line at the end, with one question mark. The student always sees the current task \
above the box they write in, so the closing question can be short and need not restate the \
whole problem. Vary your openings; do not reuse a reassurance from your last reply. Keep to the \
step you are on and to the teacher's strategy and wording."""

REPLY = """\
Your reply
One JSON object; the student sees only "message". The schema describes every field. Report \
"disclosure" honestly: the platform compares it with what was allowed, and a reply that gives \
more is redrafted or withheld. "depth_shown" is the depth in the student's own words on this \
step, never counting anything you supplied; when it could be read two ways, give the lower \
level and set "uncertain" true."""

# One line of guidance per kind of step, sent for the current step only.
KIND_LINES = {
    StepKind.EXPLAIN: (
        "On this explain step, give the whole explanation the teacher planned, with any worked "
        "example laid out line by line, then ask them to tell back one part or to use it on "
        "the next question."
    ),
    StepKind.QUESTION: "On this question step, ask for their own attempt before any help.",
    StepKind.PRACTICE: (
        "On this practice step, ask for their own attempt before any help, and keep your "
        "replies short: the work is theirs."
    ),
    StepKind.CHECK: "On this check step, ask and judge; teach only if they are wrong.",
}

# The label before the data block that closes the prompt: the student's position as JSON.
# The scripted demo responder reads the block after it.
DATA_LABEL = "The lesson and where this student is:\n"

KIND_WORDS = {
    StepKind.EXPLAIN: "an explain",
    StepKind.QUESTION: "a question",
    StepKind.PRACTICE: "a practice",
    StepKind.CHECK: "a check",
}


def fixed_parts() -> list[str]:
    """The fixed prose, in order."""
    return [CORE, DEPTH, NEVER, TEACH, TALK, REPLY]


def fixed_text() -> str:
    """The fixed prose as one text, with the slots named, for the research page."""
    core, *rest = fixed_parts()
    return "\n\n".join(
        [
            core,
            "This lesson\n{this_lesson}",
            "This step\n{this_step}",
            "Allowed right now\n{allowed}",
            "What the platform noticed\n{noticed}",
            *rest,
        ]
    )


def version(*, schema: dict) -> str:
    """A name for exactly this wording: the prose, the slot templates and the schema. v10
    is the structured prompt with depth; the hash changes with any edit to the wording."""
    text = json.dumps(
        {
            "fixed": fixed_parts(),
            "kinds": {k.value: v for k, v in KIND_LINES.items()},
            "dok": DOK_WORDS,
            "schema": schema,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"student-v10-{digest}"


# ---------- the scaffold, one block each ----------


def _join(items: list[str]) -> str:
    return "; ".join(i.strip().rstrip(".") for i in items if i.strip())


def lesson_block(brief: LessonBrief) -> str:
    about = ", ".join(
        x
        for x in (
            f'"{brief.title}"' if brief.title else "",
            brief.subject,
            brief.year_group,
            f"planned for {brief.duration_minutes} minutes",
        )
        if x
    )
    lines = [about + "."]
    if brief.objectives:
        lines.append("By the end, students will: " + _join(brief.objectives) + ".")
    if brief.prior_knowledge.strip():
        lines.append(f"What they already know: {brief.prior_knowledge.strip()}")
    if brief.strategy.strip():
        lines.append(f"How the teacher wants it taught, in their words: {brief.strategy.strip()}")
    if brief.key_terms:
        lines.append("Key terms to use and to hear back: " + ", ".join(brief.key_terms) + ".")
    if brief.support.strip():
        lines.append(f"Support for this class: {brief.support.strip()}")
    return "\n".join(lines)


def step_block(brief: LessonBrief, index: int, *, task: str | None) -> str:
    """The current step in full, the next step's questions, the rest by name, and the reference
    answer for judging only. A later step's answer is never here, so it cannot be leaked."""
    steps = brief.steps
    if not steps or index >= len(steps):
        return "The lesson has no steps."
    step = steps[index]
    lines = [
        f'Step {index + 1} of {len(steps)}, "{step.name}", {KIND_WORDS[step.kind]} step. '
        f"Goal: {step.goal.strip()}"
    ]
    if step.prompt_ideas:
        numbered = "; ".join(f'{n}) "{q}"' for n, q in enumerate(step.prompt_ideas, 1))
        lines.append(f"The questions for this step, in order: {numbered}.")
    if task:
        lines.append(f'The question on screen now: "{task}"')
    if step.success_criteria:
        lines.append("Done when: " + _join(step.success_criteria) + ".")
    else:
        lines.append("No finish line was written for this step: judge against the goal.")
    target = step.target_dok or DOK_DEFAULT
    default = "" if step.target_dok else ", the default"
    lines.append(f"Target depth: {target} ({DOK_WORDS[target]}){default}.")
    lines.append(KIND_LINES[step.kind])
    if step.reference_answer:
        lines.append(
            "For judging only, never to be stated before the rules allow the full answer: the "
            f'reference answer is "{step.reference_answer.strip()}".'
        )
    if index + 1 < len(steps):
        nxt = steps[index + 1]
        first = f' Its first question: "{nxt.prompt_ideas[0]}".' if nxt.prompt_ideas else ""
        lines.append(f'Coming next: step {index + 2}, "{nxt.name}".{first}')
        after = [s.name for s in steps[index + 2 :]]
        if after:
            lines.append("After that: " + ", ".join(f'"{n}"' for n in after) + ".")
    else:
        lines.append("This is the last step: a met answer ends the lesson.")
    return "\n".join(lines)


def _tries(n: int) -> str:
    return "one more wrong try" if n == 1 else f"{n} more wrong tries"


def allowed_block(
    brief: LessonBrief,
    *,
    attempts: int,
    allowed: Disclosure,
    guidance: list[str],
    example_button: bool = False,
    explain: bool = False,
) -> str:
    """What help may be given now, what comes next, and what never: the rules as sentences,
    with the counts already done. The teacher's guidance for this student comes last, beside
    the rules it overrides. On an explain step the explanation itself is the teacher's plan,
    so the limits are said to apply to the questions after it."""
    rules = brief.rules
    year = brief.year_group or "the year group"
    now = {
        Disclosure.FULL: (
            "Help you may give on this try: anything, including the full answer; the rules "
            "allow it now."
        ),
        Disclosure.PARTIAL: (
            "Help you may give on this try: a hint, a worked example of a similar problem, or "
            "one step of this problem done together."
        ),
        Disclosure.HINT: (
            "Help you may give on this try: a hint (a cue to the idea, or where they are stuck)."
        ),
        Disclosure.NONE: (
            "Help you may give on this try: none towards the answer; you can still explain the "
            "idea and ask questions."
        ),
    }[allowed]
    lines = [now]
    if explain:
        lines.insert(
            0,
            "This is an explain step: the explanation and worked example the teacher planned "
            "are yours to give in full, and giving them is not disclosure. The limits below "
            "apply to the question you ask after it.",
        )
    if example_button and rules.hints_allowed:
        lines.append(
            "They pressed the example button: give a short worked example of a similar problem "
            "with different numbers, never their own question or its answer, then ask them to "
            "try theirs."
        )
    if not rules.hints_allowed:
        lines.append("Hints towards the answer are not allowed in this lesson.")
    elif allowed is Disclosure.HINT:
        lines.append(
            "A worked example or a step done together: after "
            f"{_tries(rules.partial_after_attempts - attempts)}."
        )
    if rules.full_answer_after_attempts is None:
        lines.append("The answer itself: never in this lesson.")
    elif allowed is not Disclosure.FULL:
        lines.append(
            f"The answer itself: after {_tries(rules.full_answer_after_attempts - attempts)}."
        )
    lines.append(f"Your own examples and analogies: yes, when they fit {year}.")
    lines.append(
        "Writing part of the student's work: "
        + ("yes, when the lesson calls for it." if rules.may_write_for_student else "no.")
    )
    lines.append(_signals_line(rules))
    for note in rules.notes:
        lines.append(f"Also, in the teacher's words: {note.rstrip('.')}.")
    if brief.rules_text.strip():
        lines.append(f"The teacher's rules in their words: {brief.rules_text.strip()}")
    if guidance:
        said = " ".join(g.strip() for g in guidance if g.strip())
        lines.append(
            "Teacher's guidance for this student, which outranks everything above until the "
            f"teacher changes it: {said}"
        )
    else:
        lines.append("Teacher's guidance for this student: none.")
    return "\n".join(lines)


def _signals_line(rules) -> str:
    at_once = []
    kept = []
    for e in rules.escalations:
        word = SIGNAL_WORDS[e.signal].lower()
        if e.action is TriageAction.ALERT:
            at_once.append(
                word + (f" (once it has happened {e.after} times)" if e.after > 1 else "")
            )
        else:
            kept.append(word)
    always = {SignalKind.WELLBEING, SignalKind.ASKED_FOR_TEACHER}
    listed = {e.signal for e in rules.escalations}
    parts = []
    if at_once:
        parts.append(
            "The teacher asked to be told at once about: " + ", ".join(sorted(at_once)) + "."
        )
    if kept:
        parts.append("Kept in the record for them to read later: " + ", ".join(sorted(kept)) + ".")
    if not always <= listed:
        parts.append(
            "A wellbeing concern where the student may be unsafe, and a request for their "
            "teacher, always reach the teacher."
        )
    parts.append(
        "For anything else, note it and set tell_teacher only when it cannot wait for the "
        "teacher to read the record."
    )
    return " ".join(parts)


@dataclass
class Noticed:
    """What the server already counts, for the tutor to use instead of guessing."""

    attempts: int = 0
    hints: int = 0
    examples: int = 0
    worked: int = 0
    # Student messages in a row that were a bare answer with no working, and their spacing.
    bare_streak: int = 0
    bare_gap_seconds: int | None = None
    minutes_in: int | None = None
    planned_minutes: int = 30
    steps_after: int = 0
    closes_in_minutes: int | None = None
    asked_teacher_open: bool = False
    # Times the tutor has already asked for the why on this step after a right answer.
    depth_asks: int = 0
    class_slip: str | None = None
    class_slip_count: int = 0
    recalled: list[str] = field(default_factory=list)
    known: list[dict] = field(default_factory=list)


def _counted(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def noticed_block(n: Noticed) -> str:
    lines = [
        f"Wrong tries on this step: {n.attempts}. Help given on this step: "
        f"{_counted(n.hints, 'hint')}, {_counted(n.examples, 'worked example')}, "
        f"{_counted(n.worked, 'step')} done together."
    ]
    if n.bare_streak >= 2:
        gap = f", about {n.bare_gap_seconds} seconds apart" if n.bare_gap_seconds else ""
        lines.append(
            f"The last {n.bare_streak} messages were bare answers with no working{gap}: "
            "almost always guesses."
        )
    if n.minutes_in is not None:
        lines.append(
            f"{n.minutes_in} minutes in, of {n.planned_minutes} planned, with "
            f"{_counted(n.steps_after, 'step')} after this one."
        )
    if n.closes_in_minutes is not None:
        lines.append(f"The lesson closes in {n.closes_in_minutes} minutes.")
    if n.asked_teacher_open:
        lines.append("They have pressed Ask my teacher, and the teacher has not dealt with it yet.")
    if n.depth_asks:
        times = "once" if n.depth_asks == 1 else f"{n.depth_asks} times"
        lines.append(
            f"You have already asked for the why on this step {times}: do not ask again; move "
            "on with what they give."
        )
    if n.class_slip:
        lines.append(
            f"{_counted(n.class_slip_count, 'other')} in this class slipped on this step: "
            f"{n.class_slip.rstrip('.')}. Watch for it; never mention other students."
        )
    if n.recalled:
        lines.append("From this student's earlier lessons: " + " ".join(n.recalled))
    if n.known:
        facts = "; ".join(
            f"{k['topic']}: {k['met']} of {k['judged']} answers met"
            + (
                ", misconceptions: " + ", ".join(k["misconceptions"])
                if k.get("misconceptions")
                else ""
            )
            for k in n.known
        )
        lines.append(f"What the records show they know: {facts}.")
    return "\n".join(lines)


def assemble(
    *,
    brief: LessonBrief,
    index: int,
    task: str | None,
    attempts: int,
    allowed: Disclosure,
    guidance: list[str],
    noticed: Noticed,
    now: str,
    example_button: bool = False,
) -> str:
    """The whole system prompt for one turn, slots filled."""
    core, *rest = fixed_parts()
    year = brief.year_group or "secondary school"
    return "\n\n".join(
        [
            core.format(year_group=year),
            "This lesson\n" + lesson_block(brief),
            "This step\n" + step_block(brief, index, task=task),
            "Allowed right now\n"
            + allowed_block(
                brief,
                attempts=attempts,
                allowed=allowed,
                guidance=guidance,
                example_button=example_button,
                explain=index < len(brief.steps)
                and brief.steps[index].kind is StepKind.EXPLAIN
                and not brief.steps[index].reference_answer,
            ),
            "What the platform noticed\n" + noticed_block(noticed),
            *rest,
            "Right now\n" + now,
        ]
    )
