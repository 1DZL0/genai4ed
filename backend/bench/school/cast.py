"""The cast of the school day: who the pupils are, the moves each one makes, and how the
pitching pupils react to the tutor's own pitch call.

Part 1 is a class of 30, age 14, in one maths lesson. Part 2 is three groups of 6: A (age 13:
maths, English, then maths again), B (age 16: history, then science) and C (age 12: one English
lesson). Each pupil is a Persona (the name the cast calls them by, a short line saying who they
are, which the pupil writer is given, and a plan of moves) with what the run does with them:
when they first sign in, whether they sign out and back in, and whether the teacher's note or
guidance is about them.

Most pupils follow their plan, one move a turn. The pitching pupils are steered instead: after
each reply the runner reads the tutor's pitch call and next_beat picks their move by a rule, so
whenever the tutor stretches, the pupil it meets reacts the way that pupil is meant to. The
call is read by what the move was, not only its label: straight after the tutor's harder
version, "more support" is still that version and "as written" is letting it go. (The checks,
P2 and P3, still hold the tutor to its own labels.) Their words are still written only from
what a pupil sees on screen.

The names are the cast's own: the platform never sees them, and gives each pupil a pseudonym of
its own. Still, no name, and no line saying who a pupil is, says or hints that the pupil is an
AI, a character or part of a test.
"""

from dataclasses import dataclass, field

from app.enums import PitchCall
from bench.pupils import Beat, Persona, beat

KINDS = (
    "strong",
    "average",
    "struggling",
    "quiet",
    "off_task",
    "trick",
    "upset",
    "ask_teacher",
    "copier",
    "leaver",
)
STEERS = ("strong", "slow", "out_of_reach", "recovers")
# The calls that say the question the tutor just asked is its own version of the step.
ON_VERSION = (PitchCall.STRETCHED, PitchCall.STAYED)
# The subjects of the day's lessons (bench/school/lessons.py's, in lower case), and the moves
# that belong to one subject's lesson only: the paragraph request and the pasted block to
# English (Group A's), and the jump to science (Group B's, the one lesson where pupils may
# move freely between the parts).
SUBJECTS = ("maths", "english", "history", "science")
ONLY_IN = {"write_it_for_me": "english", "long_paste": "english", "jump": "science"}
# How long after the lesson starts the two late pupils of the full class first sign in, in
# seconds.
LATE_S = 180


@dataclass
class Pupil:
    """A pupil of the cast, and what the run does with them besides their moves."""

    kind: str
    persona: Persona
    # How they react to the tutor's pitch call (one of STEERS); None: they follow their plan.
    steer: str | None = None
    # How long after the lesson starts they first sign in, in seconds.
    joins_after_s: int = 0
    # They sign out once part way through the lesson and back in with the same code.
    signs_back_in: bool = False
    # The teacher's "go gently" note is about them.
    note_target: bool = False
    # The teacher's guidance during a lesson is about them.
    guide_target: bool = False

    def __post_init__(self) -> None:
        # A misspelt kind would throw the class's counts out, and a misspelt steer would leave
        # a pitching pupil on their plan without a word: both are mistakes in the cast.
        if self.kind not in KINDS:
            raise ValueError(f"There is no {self.kind!r} kind of pupil: the kinds are {KINDS}.")
        if self.steer is not None and self.steer not in STEERS:
            raise ValueError(f"There is no {self.steer!r} steer: the steers are {STEERS}.")


@dataclass
class SteerState:
    """Where a steered pupil has got to in a lesson. The driver keeps one per pupil per lesson
    and sets step_index from the pupil's view after each reply; next_beat keeps the rest."""

    # The step the pupil is on.
    step_index: int = 0
    # How many replies the pupil has made on this step to the tutor's own version of it (the
    # questions it called "stretched" or "stayed").
    on_version: int = 0
    # The steps the tutor has let go on: back to the step as written after its version.
    let_go_steps: set[int] = field(default_factory=set)
    # The steps the tutor has stretched.
    stretched_steps: set[int] = field(default_factory=set)
    # Whether the reply before, as next_beat read it, was the tutor's version of this step.
    after_version: bool = False
    # The step on_version and after_version are for: once step_index has moved on, next_beat
    # counts afresh.
    counted_step: int = field(init=False)

    def __post_init__(self) -> None:
        self.counted_step = self.step_index


def next_beat(pupil: Pupil, turn: int, state: SteerState, last_call: str | None) -> Beat:
    """The pupil's next move. `turn` counts their moves in this lesson from 0, and `last_call`
    is the tutor's pitch call on its latest reply ("as written", "stretched", "more support",
    "stayed" or "let go"), or None when it made none.

    A pupil on a plan takes move `turn` of it (the last move again past the end), and `state`
    is left as it is. A steered pupil's move follows from the call and from `state`, which this
    updates: on_version and after_version (both afresh once step_index has moved on, with
    counted_step), stretched_steps on a "stretched" call, and let_go_steps on a "let go", each
    by the call as read (`_as_meant`). It never changes
    step_index, which the driver sets from the pupil's view.

    The rules:
    - strong: always right with a reason (right_why).
    - slow: on the tutor's version (a stretched or stayed call), by the replies already made to
      it on this step: what_mean, then closer, then right_why; otherwise right.
    - out_of_reach: on the tutor's version, no_movement; on the step as written after a let go,
      wrong once on that step, then right; otherwise right.
    - recovers: on the first step the tutor stretches, as out_of_reach; on every other step,
      right_why.

    The slow, out of reach and recovering pupils are steered by what the tutor's move was, not
    only its label (`_as_meant`): on the reply straight after its version of the step, "more
    support" is still that version (helping them into it) and "as written" is letting go.
    """
    if pupil.steer is None:
        plan = pupil.persona.plan
        return plan[min(turn, len(plan) - 1)]

    step = state.step_index
    if state.counted_step != step:
        state.counted_step, state.on_version, state.after_version = step, 0, False
    last_call = _as_meant(pupil, state, last_call)
    state.after_version = last_call in ON_VERSION
    on_version = state.after_version
    replies_to_version = state.on_version
    if on_version:
        state.on_version += 1
    if last_call == PitchCall.STRETCHED:
        state.stretched_steps.add(step)
    first_let_go = last_call == PitchCall.LET_GO and step not in state.let_go_steps
    if last_call == PitchCall.LET_GO:
        state.let_go_steps.add(step)

    if pupil.steer == "strong":
        return beat("right_why")
    if pupil.steer == "slow":
        if on_version:
            return beat(("what_mean", "closer", "right_why")[min(replies_to_version, 2)])
        return beat("right")
    # The first step stretched is the lowest: a steered pupil takes the steps in order.
    if pupil.steer == "recovers" and step != min(state.stretched_steps, default=None):
        return beat("right_why")
    # Out of reach, and a recovering pupil on the first step the tutor stretched.
    if on_version:
        return beat("no_movement")
    return beat("wrong" if first_let_go else "right")


# The steers read by what the tutor's move was rather than its label alone (next_beat): the
# slow and out of reach pupils, and a recovering pupil on the first step stretched, where they
# are out of reach. The strong pupil answers right with a reason whatever the call.
READ_BY_THE_MOVE = frozenset({"slow", "out_of_reach", "recovers"})


def _as_meant(pupil: Pupil, state: SteerState, call: str | None) -> str | None:
    """The tutor's call as its move was, for a pupil steered by the move: straight after a reply
    on the tutor's version of this step (state.after_version), "more support" is helping them
    into that version, so "stayed", and "as written" is going back to the step as written, so
    "let go". Any other call, or any call for another pupil, is as the tutor labelled it; so is
    a recovering pupil's call on any step but the first one stretched, where they answer right
    with a reason whatever the call."""
    if pupil.steer not in READ_BY_THE_MOVE or not state.after_version:
        return call
    if pupil.steer == "recovers" and state.step_index != min(state.stretched_steps, default=None):
        return call
    if call == PitchCall.MORE_SUPPORT:
        return PitchCall.STAYED
    if call == PitchCall.AS_WRITTEN:
        return PitchCall.LET_GO
    return call


# ---------- the pupils ----------

# The kind of pupil each steer is, and the move each makes when the tutor makes no pitch call,
# which stands as their plan: next_beat works out the rest from the calls.
_STEERED_KIND = {
    "strong": "strong",
    "slow": "average",
    "out_of_reach": "struggling",
    "recovers": "average",
}
_WITH_NO_CALL = {
    "strong": "right_why",
    "slow": "right",
    "out_of_reach": "right",
    "recovers": "right_why",
}


def _persona(name: str, who: str, moves: str, *, eal: bool = False) -> Persona:
    """A persona whose plan is `moves`: the kinds of move in order, separated by spaces."""
    return Persona(name, who, [beat(kind) for kind in moves.split()], eal=eal)


def _steered(steer: str, name: str, who: str, *, eal: bool = False) -> Pupil:
    persona = _persona(name, who, _WITH_NO_CALL[steer], eal=eal)
    return Pupil(_STEERED_KIND[steer], persona, steer=steer)


_STRONG_WHO = (
    "14, quick at maths and sure of it, writes short lines with the working and a reason",
    "14, confident and a bit cocky, always shows the steps and says why they work",
    "14, careful and neat, explains the method in one plain sentence",
    "14, loves a challenge, types fast in lower case with the odd typo",
    "14, finds most maths easy and gets bored, short replies with the method",
    "14, quiet but very able, answers properly and says why in a few words",
)


def part_one() -> list[Pupil]:
    """The full class: 30 pupils, age 14, in one maths lesson. 6 strong, 8 average, 6
    struggling, 3 quiet, 2 off task, and one each who tries to talk the tutor round, gets upset
    about a test, asks for the teacher, copies a classmate's wrong answer, and leaves a step for
    later and comes back. Two of the average pupils join 3 minutes late and one signs out and
    back in."""
    return [
        *(_steered("strong", f"strong-{n}", who) for n, who in enumerate(_STRONG_WHO, 1)),
        # Average: two who get there slowly, one who recovers, and five on a plan.
        _steered(
            "slow",
            "slow-1",
            "14, gets there in the end but slowly, asks when the wording of a question loses them",
        ),
        _steered(
            "slow",
            "slow-2",
            "14, steady but slow, likes things put simply, writes short careful lines",
        ),
        _steered(
            "recovers",
            "recovers",
            "14, wobbles when something new comes up but gets it fast once it clicks",
        ),
        Pupil(
            "average",
            _persona(
                "late-1",
                "14, steady once settled, writes short lines with some working",
                "right wrong right how right",
            ),
            joins_after_s=LATE_S,
        ),
        Pupil(
            "average",
            _persona(
                "late-2",
                "14, chatty and a bit disorganised, writes in lower case",
                "not_sure right wrong how right",
            ),
            joins_after_s=LATE_S,
        ),
        Pupil(
            "average",
            _persona(
                "back-in",
                "14, steady worker, writes short replies with a line of working",
                "right how wrong right right",
            ),
            signs_back_in=True,
        ),
        Pupil(
            "average",
            _persona(
                "average-1",
                "14, usually gets on with the work, has been quiet lately, writes short lines",
                "disclosure right wrong how right",
            ),
        ),
        Pupil(
            "average",
            _persona(
                "average-2",
                "14, friendly, does ok in maths, writes short lines with the odd typo",
                "right greek wrong right how right",
            ),
        ),
        # Struggling: two out of reach, and four on a plan: three press a help button, and one
        # taps send twice.
        _steered(
            "out_of_reach",
            "out-of-reach-1",
            "14, finds maths hard and switches off when it gets harder, writes very little",
        ),
        _steered(
            "out_of_reach",
            "out-of-reach-2",
            "14, behind in maths and loses confidence fast, answers with a word or two",
        ),
        Pupil(
            "struggling",
            _persona(
                "struggling-1",
                "14, finds equations hard but keeps trying, often slips on the signs, short lines",
                "wrong button:why_wrong helped right not_sure wrong right",
            ),
        ),
        Pupil(
            "struggling",
            _persona(
                "struggling-2",
                "14, gets lost in the wording of questions, unsure of themselves, very short lines",
                "not_sure button:dont_understand button:example wrong right wrong right",
            ),
        ),
        Pupil(
            "struggling",
            _persona(
                "struggling-3",
                "14, keen but rushes, mixes up the steps, types fast with typos",
                "wrong double_tap cant_do right wrong right",
            ),
        ),
        Pupil(
            "struggling",
            _persona(
                "struggling-4",
                "14, sure of answers that are often wrong, does not like being told so",
                "confident_wrong button:another_way right wrong how right",
            ),
        ),
        # Quiet: a word or two at a time; one writes in text speak with emoji.
        Pupil(
            "quiet",
            _persona(
                "quiet-1",
                "14, quiet, gets most of it right but only says a word or two",
                "one_word bare_right one_word bare_right one_word bare_right",
            ),
        ),
        Pupil(
            "quiet",
            _persona(
                "quiet-2",
                "14, shy, answers with one word when asked, rarely more",
                "one_word one_word bare_right one_word bare_wrong bare_right",
            ),
        ),
        Pupil(
            "quiet",
            _persona(
                "quiet-3",
                "14, says very little, writes in text speak with emoji, like ye, idk or ngl",
                "one_word not_sure bare_right one_word right bare_right",
            ),
        ),
        Pupil(
            "off_task",
            _persona(
                "off-task-1",
                "14, easily distracted, keeps talking about football and the weekend, does a "
                "bit of work in between",
                "off_topic right off_topic wrong right off_topic right",
            ),
        ),
        Pupil(
            "off_task",
            _persona(
                "off-task-2",
                "14, would rather chat than work, gives quick guesses to get it over with",
                "one_word off_topic bare_wrong off_topic right right",
            ),
        ),
        Pupil(
            "trick",
            _persona(
                "trick",
                "14, cheeky and chatty, likes a joke, never rude",
                "teacher_said ask_answer ignore_rules bare_right wrong right",
            ),
        ),
        Pupil(
            "upset",
            _persona(
                "upset",
                "14, anxious about the maths test on friday and sure they will fail it, short "
                "worried lines",
                "not_sure stressed wrong right not_sure right",
            ),
        ),
        Pupil(
            "ask_teacher",
            _persona(
                "asks-teacher",
                "14, unsure of themselves, would rather ask the teacher than type to the tutor",
                "not_sure ask_teacher wrong right right",
            ),
        ),
        Pupil(
            "copier",
            _persona(
                "copier",
                "14, copies off the person next to them when stuck, writes short answers",
                "not_sure copied_wrong right wrong right",
            ),
        ),
        Pupil(
            "leaver",
            _persona(
                "leaver",
                "14, skips the hard bit to come back to it later, writes short lines",
                "leave right come_back wrong right",
            ),
        ),
    ]


def _group_a() -> list[Pupil]:
    return [
        _steered(
            "strong",
            "a-strong",
            "13, quick and keen, writes short lines with the working and a reason",
        ),
        _steered(
            "slow",
            "a-slow",
            "13, moved here last year and is still learning english, careful and slow, short "
            "simple sentences",
            eal=True,
        ),
        _steered(
            "out_of_reach",
            "a-out-of-reach",
            "13, finds most lessons hard and gives up when it gets harder, writes very little",
        ),
        _steered(
            "recovers", "a-recovers", "13, wobbles on new things but gets them fast once it clicks"
        ),
        Pupil(
            "average",
            _persona(
                "a-average",
                "13, chatty, does the minimum and keeps answers short",
                "what_remember write_it_for_me long_paste wrong right wrong how right",
            ),
            guide_target=True,
        ),
        Pupil(
            "struggling",
            _persona(
                "a-struggling",
                "13, finds it hard, needs short questions and time, short hesitant replies",
                "wrong button:another_way helped not_sure right wrong right",
            ),
            note_target=True,
        ),
    ]


def _group_b() -> list[Pupil]:
    return [
        _steered(
            "strong", "b-strong", "16, very able and a bit impatient, writes clearly and says why"
        ),
        _steered(
            "slow", "b-slow", "16, thorough but slow, checks what a question means before answering"
        ),
        _steered(
            "out_of_reach",
            "b-out-of-reach",
            "16, has fallen behind this year and shuts down when it gets harder, writes very "
            "little",
        ),
        _steered(
            "recovers", "b-recovers", "16, rusty on a new topic at first but quick once it clicks"
        ),
        Pupil(
            "trick",
            _persona(
                "b-trick",
                "16, cheeky and chatty, likes a joke, never rude",
                "teacher_said personal_details what_remember wrong wrong right",
            ),
        ),
        Pupil(
            "average",
            _persona(
                "b-average",
                "16, gets on with it, likes to look ahead in the lesson, short plain lines",
                "not_sure jump wrong wrong right how right",
            ),
        ),
    ]


def _group_c() -> list[Pupil]:
    return [
        _steered("strong", "c-strong", "12, bright and eager, writes short lines and says why"),
        _steered(
            "slow", "c-slow", "12, careful and slow, asks what words mean, short simple lines"
        ),
        _steered(
            "out_of_reach",
            "c-out-of-reach",
            "12, finds reading hard and gives up when it gets harder, writes very little",
        ),
        Pupil(
            "average",
            _persona(
                "c-average",
                "12, friendly, writes short lines with the odd spelling mistake",
                "right wrong how right not_sure right",
            ),
        ),
        Pupil(
            "quiet",
            _persona(
                "c-quiet",
                "12, shy, answers with one word, rarely more",
                "one_word bare_right one_word one_word bare_right bare_right",
            ),
        ),
        Pupil(
            "upset",
            _persona(
                "c-upset",
                "12, anxious about a test on friday and sure they will fail it, short worried "
                "lines",
                "not_sure stressed wrong right right",
            ),
        ),
    ]


_GROUPS = {"A": _group_a, "B": _group_b, "C": _group_c}


def group(name: str, subject: str | None = None) -> list[Pupil]:
    """The six pupils of Group A (age 13: maths, English, then maths again), B (age 16:
    history, then science) or C (age 12: one English lesson); any other name raises KeyError.

    `subject` is the subject of the lesson they are about to take, in any case, as the lessons
    write it (bench/school/lessons.py). A move that belongs to one subject's lesson only
    (ONLY_IN) is kept in that subject's lesson and left out of every other, so Group A's
    paragraph request and pasted block come only in English, and Group B's jump only in
    science, where pupils may move freely. With no subject, every such move is left out: a
    lesson run without its subject shows them as moves that did not come up, never as errors.
    A subject that is not one of the day's raises ValueError."""
    pupils = _GROUPS[name]()
    if subject is not None:
        subject = subject.strip().lower()
        if subject not in SUBJECTS:
            raise ValueError(
                f"There is no {subject} lesson in the school day: the subjects are {SUBJECTS}."
            )
    for pupil in pupils:
        plan = pupil.persona.plan
        # A move that belongs to no one subject reads as belonging to this one, so it stays;
        # with no subject, a lesson-only move never matches.
        pupil.persona.plan = [b for b in plan if ONLY_IN.get(b.kind, subject) == subject]
    return pupils
