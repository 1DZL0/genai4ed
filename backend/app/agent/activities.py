"""The kinds of activity a lesson can be: the headings a teacher picks from, and under each
the kinds the agent works out from the teacher's words.

This file is the one place the list lives. The teacher's screen is sent the headings, the
prompts are written from the headings and their kinds, and the researchers' coding guide is
generated from the same rows. Adding a kind is one line under its heading.

A kind says whether its work has right answers or is judged against criteria, because that is
what the tutor needs to know to judge a student's answer; the heading does not decide it.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.enums import ActivityKind


@dataclass(frozen=True)
class Kind:
    name: str
    shape: ActivityKind
    # What the name covers, where the name alone leaves it open.
    detail: str = ""


@dataclass(frozen=True)
class Heading:
    key: str
    label: str
    # One line on what such a lesson looks like. Kept as data: the drafting agent was told
    # it until teacher-v25, where no reply on the live set needed it.
    shape: str
    # One line on how to teach it, for the tutor.
    teaching: str
    kinds: tuple[Kind, ...] = ()


def _right(name: str, detail: str = "") -> Kind:
    """A kind whose steps have an answer the student works out."""
    return Kind(name, ActivityKind.ANSWERS, detail)


def _judged(name: str, detail: str = "") -> Kind:
    """A kind judged against criteria, with no single answer."""
    return Kind(name, ActivityKind.OPEN, detail)


_FORMS = "argumentative, narrative or descriptive"
_PROBLEMS = "word problems, equations, calculations, graphs, diagrams"
_ANSWERS = "explaining a concept, comparing and contrasting, answering from evidence"

HEADINGS: tuple[Heading, ...] = (
    Heading(
        "writing",
        "Writing tasks",
        "a brief for the piece, then a plan, a draft and a revision; each finish line says "
        "what the writing must show",
        "coach the student's own draft against the criteria one point at a time, and never "
        "write a sentence of it for them",
        (
            _judged("essay writing", _FORMS),
            _judged("letter writing", _FORMS),
            _judged("paragraph writing", _FORMS),
            _judged("creative writing", "a story, a dialogue"),
            _judged("summary writing"),
            _judged("report writing"),
        ),
    ),
    Heading(
        "maths",
        "Mathematics tasks",
        "a way in, then problems that get harder; each step has an answer or a justification "
        "to judge against",
        "have the student show each line of working, find where it first goes wrong, and "
        "help one notch at a time",
        (
            _right("one-step problems", _PROBLEMS),
            _right("multi-step problems", _PROBLEMS),
            _judged("mathematical reasoning and justification"),
            _right("error identification and correction"),
            _right("data interpretation and analysis"),
            _right("pattern recognition and generalisation"),
            _judged("mathematical modelling"),
            _judged("comparing and evaluating solutions"),
        ),
    ),
    Heading(
        "open_questions",
        "Open-ended question answering",
        "a few questions that ask for an explanation, a comparison or evidence, each with "
        "what a good answer must include",
        "ask for the reason behind an answer and what supports it; judge against what a good "
        "answer includes, not one wording",
        (
            _right("short-answer questions", _ANSWERS),
            _judged("extended-answer questions", _ANSWERS),
        ),
    ),
    Heading(
        "choice",
        "Multiple-choice / Cloze tasks",
        "short questions with options or blanks, each with its right answer and why the "
        "tempting wrong ones are wrong",
        "after a choice ask why; on a wrong one point at what rules it out before giving "
        "anything away",
        (
            _right("multiple choice", "one answer or several to select"),
            _right("fill-in-the-blanks"),
            _right("true / false questions"),
        ),
    ),
    Heading(
        "reading",
        "Reading comprehension",
        "the text first, then questions that go from what it says to what it implies; each "
        "answer points back to the text",
        "send the student back to the words of the text and ask where it says so; never "
        "summarise the text for them",
        (
            _right("identifying main ideas"),
            _right("making inferences", "bridging, elaborative"),
            _judged("comparing multiple texts"),
            _judged("evaluating arguments"),
        ),
    ),
    Heading(
        "critical",
        "Critical thinking and evaluation",
        "a claim, an argument or a set of solutions to weigh, then steps that ask for a "
        "judgement and the grounds for it",
        "ask for the grounds of each judgement and for the other side; judge the reasoning, "
        "not which side they take",
        (
            _judged("evaluating claims and evidence"),
            _right("identifying misconceptions"),
            _judged("identifying bias"),
            _judged("evaluating alternative solutions"),
        ),
    ),
    Heading(
        "inquiry",
        "Scientific inquiry / Investigation",
        "a question to investigate, then a hypothesis, a plan or some results to read, and a "
        "conclusion tied to the evidence",
        "ask what they expect and why, what would count as evidence, and whether the data "
        "supports the conclusion they draw",
        (
            _judged("formulating hypotheses"),
            _judged("designing experiments"),
            _right("interpreting experimental results"),
            _right("drawing conclusions from data"),
        ),
    ),
)

# What a teacher picks when none of the seven fits. Nothing is listed under it: the agent
# names the kind in its own words and the lesson is recorded as not on the list.
OTHER = Heading(
    "other",
    "Something else",
    "whatever the teacher describes, built from their words",
    "teach it as the lesson's steps and finish lines say",
)

# Everything a teacher can press, in the order the screen shows it.
PICKS: tuple[Heading, ...] = (*HEADINGS, OTHER)


def heading(key: str) -> Heading | None:
    """The heading with this key, or None when there is no such heading."""
    return next((h for h in PICKS if h.key == key), None)


def find_kind(name: str, among: Iterable[Heading] = HEADINGS) -> tuple[Heading, Kind] | None:
    """The kind called this and the heading it is under, however the name is capitalised."""
    wanted = " ".join(name.lower().split())
    if not wanted:
        return None
    return next(((h, k) for h in among for k in h.kinds if k.name.lower() == wanted), None)


def pressed(keys: Iterable[str]) -> list[str]:
    """What a teacher pressed, as the headings' keys in the screen's order, each once. A key
    the screen does not offer is an error."""
    wanted = set(keys)
    unknown = wanted - {h.key for h in PICKS}
    if unknown:
        raise ValueError(f"Not an activity that can be picked: {', '.join(sorted(unknown))}.")
    return [h.key for h in PICKS if h.key in wanted]


# How the line under a teacher's words opens when they pressed a heading. The agent reads the
# pick there, in the words the screen used.
PICKED = "The activity I picked: "


def picked_line(keys: Iterable[str]) -> str:
    """What was pressed, as the one line kept under the teacher's words. Nothing pressed is
    no line."""
    labels = [h.label for h in PICKS if h.key in set(keys)]
    return f"{PICKED}{', '.join(labels)}." if labels else ""


def for_prompt() -> str:
    """The headings and the kinds under each, as the drafting agent is told them: a line a
    heading."""
    lines = []
    for h in HEADINGS:
        kinds = "; ".join(f"{k.name} ({k.detail})" if k.detail else k.name for k in h.kinds)
        lines.append(f'- {h.label} ("{h.key}"): {kinds}.')
    lines.append(
        f'- {OTHER.label} ("{OTHER.key}"): when none of these fits; the kind in your own words.'
    )
    return "\n".join(lines)


def for_screen() -> list[dict[str, str]]:
    """What the teacher's page is sent: the picks, and none of the kinds under them."""
    return [{"key": h.key, "label": h.label} for h in PICKS]
