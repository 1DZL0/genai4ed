"""The one wording every teacher's turns are written from.

There are no planning switches: every teacher is asked first, with steps that name their
objective. The fixed prompt, the reply shape and the block the server writes each turn are one
wording under one version, so every reply in the record says which wording it was written from.
"""

import re

from app.agent import thread
from app.agent.teacher_prompt import MODULES, SYSTEM, TALK
from tests.test_activity_in_the_lesson import ASKS, scripted
from tests.test_thread import press, say
from tests.test_where_the_lesson_stands import latest_turn, stands, topic_drafted

# The version every reply is written under since every teacher is asked first, with the lesson
# rule on pitching and the days a note on one student is kept.
TODAY = "teacher-v27-d3ff25ed"

# What follows the fixed wording in the part of a call that is cached: the reply's shape.
SHAPE = "\n\nReply with a single JSON object"

# The sentences of "How to talk" that came over word for word from the wording before it.
KEPT = (
    "under 600 characters",
    "Ask only for what is missing",
    "Everything else you fill in and mark to check",
    "the help rules stay at their defaults unless the teacher stated their own",
    "What age are your Year 8 students?",
)


def opens_with(call: dict, wording: str) -> bool:
    """Whether a call to the model opened with this wording, as the part that is cached."""
    cached = call["cache_prefix"]
    return cached.startswith(wording + SHAPE) and call["system"].startswith(cached)


def test_the_version_names_this_wording():
    assert thread.PROMPT_VERSION == TODAY
    # The column the version is kept in holds 32 characters.
    assert len(TODAY) <= 32


def test_the_version_covers_the_prompt_the_reply_shape_and_the_blocks_sentences():
    same = thread._version("teacher-v27-", SYSTEM, thread.STANDS, thread.TeacherTurnServing)
    assert same == TODAY
    assert thread._version("teacher-v27-", SYSTEM + " ", thread.STANDS) != TODAY
    assert thread._version("teacher-v27-", SYSTEM, thread.STANDS[:-1]) != TODAY
    assert thread._version("teacher-v27-", SYSTEM, thread.STANDS, thread.TeacherTurnOut) != TODAY
    # Every sentence of the block that is not about one lesson's own heading is covered.
    for sentence in (thread.STANDS_FOLLOW_UP, thread.STANDS_IN_WORDS, thread.STANDS_THREE):
        assert sentence in thread.STANDS


async def test_every_teacher_is_sent_the_one_wording_under_its_version(app, client, classroom, db):
    model = scripted(app, ASKS, ASKS)

    # One with a lesson in focus, and one who has none yet.
    await say(client, classroom, "A lesson on fractions.")
    assert opens_with(model.calls[-1], SYSTEM)
    assert (await latest_turn(db)).prompt_version == TODAY
    await say(client, classroom, "A lesson on fractions.", teacher=classroom.other_teacher)
    assert opens_with(model.calls[-1], SYSTEM)
    assert (await latest_turn(db)).prompt_version == TODAY


async def test_the_reply_shape_the_agent_is_given_has_steps_that_name_their_objective(
    app, client, classroom
):
    model = scripted(app, ASKS)

    await say(client, classroom, "A lesson on fractions.")

    cached = model.calls[-1]["cache_prefix"]
    assert '"objective"' in cached
    for gone in ('"easier"', '"deeper"'):
        assert gone not in cached, gone


def test_the_talk_keeps_the_house_rules():
    assert SYSTEM == "\n".join(MODULES.values())
    assert MODULES["talk"] is TALK
    assert TALK.startswith("How to talk\n")
    assert len(SYSTEM) < 7000
    assert 'Teacher: "' in TALK and 'Your reply: "' in TALK
    assert len(re.findall(r"\bnever\b", SYSTEM, re.IGNORECASE)) <= 1
    for rule in KEPT:
        assert SYSTEM.count(rule) == 1, rule
    # Where the tutor settings sit is said in "The class", not in how to talk about a lesson.
    assert "under the box" not in TALK


def test_the_talk_says_what_is_asked_for_before_a_draft():
    said = TALK.lower()
    for needed in ("objective", "age", "length"):
        assert needed in said, needed
    assert "two at most" in said
    assert "you decide" in said
    assert "follows up a shared difficulty" in said
    # Run v26-ask-x-sentback: given a kind of task or the teacher's own questions, with the age
    # and the length, the agent drafted, wrote the objectives itself and was sent back (7 of 12).
    assert "a kind of task or their own questions" in said
    # The kind of activity is the agent's to guess, never asked for.
    assert "you do not ask for it" in said


# ---------- the screen has no activity box ----------
# Run v26-switched: to a teacher whose screen had no headings the agent still said "Pick a
# heading below", so the server says each turn that the kind of activity is said in words.


async def test_the_agent_is_told_the_kind_of_activity_is_said_in_words(app, client, classroom):
    model = scripted(app, ASKS)

    await say(client, classroom, "A lesson on fractions.")

    block = stands(model)
    assert block.endswith(thread.STANDS_IN_WORDS)
    for gone in ("Nothing is pressed", "They pressed", "headings appear under your reply"):
        assert gone not in block, gone
    # The sentence as the agent reads it this turn names what the screen does not have, and
    # says the kind is said in words.
    last = block[len(block) - len(thread.STANDS_IN_WORDS) :]
    for not_there in ("activity box", "headings to press"):
        assert not_there in last, not_there
    assert "in words" in last
    # The Tutor line is still on the screen, so nothing in the block says it is gone.
    assert "tutor" not in block.lower()


async def test_the_follow_up_button_is_told_the_same(app, client, classroom):
    model = scripted(app, topic_drafted(title="Where plants get food", topics=["plant food"]))

    await press(client, classroom, "follow_up", text="plants get food from the soil")

    block = stands(model)
    assert thread.STANDS_FOLLOW_UP in block
    assert block.endswith(thread.STANDS_IN_WORDS)
