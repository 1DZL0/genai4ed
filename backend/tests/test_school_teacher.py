"""The teacher of the school day, driving the platform over HTTP as a teacher's browser does:
signing in, making a class with join codes, describing a lesson to the class agent until it
drafts one (or giving up after two nudges), approving and running it, pressing the buttons,
reading the class view, asking the agent and changing their own settings.

Each user has a client of their own (their own cookie jar) on the app in this process, the
class agent is scripted, and demo sign-in is switched on as the demo tests switch it on.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from app.agent import llm
from app.config import get_settings
from app.demo import MATHS
from bench.school.lessons import GROUP_LESSONS, PART_ONE, TEXTS, LessonPlan
from bench.school.teacher import NUDGE, NotDone, Seat, Teacher

# PART_ONE as the class agent drafts it: everything the platform needs before approving it.
DRAFT = {
    "title": "Linear equations: unknown on both sides",
    "subject": "maths",
    "age": 14,
    "activity": "answers",
    "duration_minutes": 40,
    "prior_knowledge": "Two-step equations.",
    "objectives": ["Solve equations with the unknown on both sides and check the answer"],
    "steps": [
        {
            "name": "Warm up",
            "kind": "question",
            "goal": "Solve 3x + 4 = 19",
            "prompt_ideas": ["Solve 3x + 4 = 19. What's your first step?"],
            "success_criteria": ["x = 5 with working"],
            "reference_answer": "5",
        },
        {
            "name": "Both sides",
            "kind": "practice",
            "goal": "Solve 5x + 3 = 2x + 18",
            "prompt_ideas": ["Solve 5x + 3 = 2x + 18, then put your answer back in."],
            "success_criteria": ["x = 5 with the x terms collected and the answer checked"],
            "reference_answer": "5",
        },
        {
            "name": "Brackets",
            "kind": "practice",
            "goal": "Solve 2(x + 3) = 4x - 2",
            "prompt_ideas": ["Solve 2(x + 3) = 4x - 2."],
            "success_criteria": ["Expands the brackets; x = 4"],
            "reference_answer": "4",
        },
        {
            "name": "Word problem",
            "kind": "check",
            "goal": "Turn a word problem into an equation and solve it",
            "prompt_ideas": [
                "I think of a number, times it by 5 and add 3. I get the same as doubling it "
                "and adding 18. What is my number?"
            ],
            "success_criteria": ["Writes 5x + 3 = 2x + 18 and solves it: 5"],
            "reference_answer": "5",
        },
    ],
    "rules_text": "Hints any time, a worked step after one wrong try, never give the final answer.",
    "topics": ["linear equations"],
}
DRAFTS = {"reply": "Here it is: four steps, 40 minutes.", "show": "lesson", "brief": DRAFT}
# The same lesson with no finish line on step 2: drafted, but it can't be approved yet.
NOT_READY = {
    **DRAFT,
    "steps": [
        DRAFT["steps"][0],
        {**DRAFT["steps"][1], "success_criteria": []},
        *DRAFT["steps"][2:],
    ],
}
# The sample lesson every new teacher has, with one question reworded: a change the teacher's
# list of lessons can't see (the same title, subject, steps, length and readiness).
REWORDED = MATHS.model_dump(mode="json")
REWORDED["steps"][0]["prompt_ideas"] = ["What would you do first to solve 3x + 4 = 19?"]
# A reply that only asks, and drafts nothing.
ASKS = {"reply": "Happy to help. Should the word problem be about money?", "show": "nothing"}
# How step 1 opens for a pupil, in the shape the tutor answers in.
OPENS = {"message": "Hi! Let's start: solve 3x + 4 = 19.", "move": "ask"}


def brief(title: str, age: int, topics: list[str], steps: int = 3) -> dict:
    """A maths brief the platform can approve, with `steps` short steps."""
    return {
        "title": title,
        "subject": "maths",
        "age": age,
        "activity": "answers",
        "duration_minutes": 40,
        "objectives": [f"Work out {topics[0]} without a calculator"],
        "steps": [
            {
                "name": f"Part {n}",
                "kind": "practice",
                "goal": f"Question {n}",
                "prompt_ideas": [f"Question {n}"],
                "success_criteria": ["The right answer"],
                "reference_answer": str(n),
            }
            for n in range(1, steps + 1)
        ],
        "topics": topics,
    }


class NoAnswerTo(httpx.AsyncBaseTransport):
    """The app, except that requests to one path never get an answer: they time out."""

    def __init__(self, app, path: str) -> None:
        self.app = httpx.ASGITransport(app=app)
        self.path = path

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == self.path:
            raise httpx.ReadTimeout("The read timed out.", request=request)
        return await self.app.handle_async_request(request)


@asynccontextmanager
async def new_browser(app) -> AsyncIterator[httpx.AsyncClient]:
    """One user's browser: a client with a cookie jar of its own."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    # The cookie does the work, not the test-only header.
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)


@pytest.fixture
async def browser(app, demo_on) -> AsyncIterator[httpx.AsyncClient]:
    async with new_browser(app) as client:
        yield client


def agent_replies(app, *replies: dict) -> llm.ScriptedClient:
    """The class agent's next replies, exactly these. It keeps what it was asked."""
    agent = llm.ScriptedClient(list(replies))
    app.dependency_overrides[llm.get_llm_client] = lambda: agent
    return agent


async def thread_of(browser: httpx.AsyncClient) -> dict:
    return (await browser.get("/api/teacher/thread")).json()


async def lessons_of(browser: httpx.AsyncClient) -> list[dict]:
    """The teacher's list of lessons: the newest version of each, newest first."""
    return (await browser.get("/api/teacher/thread/lessons")).json()["lessons"]


async def test_a_teacher_makes_a_class_of_thirty_with_join_codes(app, browser):
    teacher = Teacher(browser, "ms-okafor")
    await teacher.sign_in()
    class_id, seats = await teacher.make_class("9S", 30)

    assert uuid.UUID(class_id)
    assert len(seats) == 30 and all(isinstance(seat, Seat) for seat in seats)
    assert all(seat.code for seat in seats)
    assert len({seat.pseudonym for seat in seats}) == 30
    assert all(isinstance(seat.student_id, str) and uuid.UUID(seat.student_id) for seat in seats)
    # Each code is its own pupil's: it signs them in from their own browser.
    async with new_browser(app) as pupil:
        signed = await pupil.post("/api/auth/join", json={"code": seats[0].code})
    assert signed.status_code == 200 and signed.json()["pseudonym"] == seats[0].pseudonym


async def test_drafting_approving_and_running_gives_a_session(app, browser):
    agent = agent_replies(app, DRAFTS)
    teacher = Teacher(browser, "mr-osei")
    await teacher.sign_in()
    class_id, seats = await teacher.make_class("9S", 3)

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.lesson_id and drafted.asked == 1 and drafted.reason == ""
    # The words went to the agent once, as the teacher typed them, and no nudge followed.
    [asked] = agent.calls
    assert asked["messages"][-1]["content"] == PART_ONE.words
    assert drafted.lesson_id == (await thread_of(browser))["focus"]["lesson_id"]

    await teacher.approve(drafted.lesson_id)
    session_id = await teacher.run(drafted.lesson_id, class_id)
    assert uuid.UUID(session_id)
    card, seconds = await teacher.class_view()
    assert (card["type"], card["session_id"]) == ("class", session_id)
    assert {s["pseudonym"] for s in card["students"]} == {seat.pseudonym for seat in seats}
    assert isinstance(seconds, float) and seconds >= 0


@pytest.mark.parametrize("shown", [{}, {"show": "lessons"}], ids=["nothing shown", "the list"])
async def test_a_draft_the_agent_does_not_put_on_screen_is_still_found(app, browser, shown):
    """What goes on screen is the agent's choice, and nothing is its default. A draft it does
    not show leaves nothing in focus, but it is in the teacher's lessons all the same."""
    agent_replies(app, {"reply": "Here it is.", **shown, "brief": DRAFT})
    teacher = Teacher(browser, "ms-lindqvist")
    await teacher.sign_in()

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.lesson_id and drafted.asked == 1 and drafted.reason == ""
    assert (await thread_of(browser))["focus"] is None
    lessons = (await browser.get("/api/teacher/thread/lessons")).json()["lessons"]
    [made] = [lesson for lesson in lessons if lesson["lesson_id"] == drafted.lesson_id]
    assert (made["status"], made["steps"], made["title"]) == ("draft", 4, DRAFT["title"])


async def test_an_agent_that_only_asks_is_given_two_nudges_then_the_draft_is_marked_failed(
    app, browser
):
    agent = agent_replies(app, ASKS, ASKS, ASKS)
    teacher = Teacher(browser, "ms-mensah")
    await teacher.sign_in()

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.lesson_id is None and drafted.asked == 3
    assert "did not draft" in drafted.reason
    # The words once, then the nudge twice and no more.
    said = [m["text"] for m in (await thread_of(browser))["messages"] if m["role"] == "teacher"]
    assert said == [PART_ONE.words, NUDGE, NUDGE]
    assert NUDGE == "That's everything, please draft it."
    assert len(agent.calls) == 3


async def test_a_message_the_agent_could_not_answer_counts_as_asked(app, browser):
    """The platform keeps a message the agent could not answer (503), so the nudge after it is
    the teacher trying again. An agent that never answers leaves the lesson not drafted."""

    def unavailable_once(purpose, system, messages):
        if len(agent.calls) == 1:
            raise llm.LLMError("The model took too long.")
        return DRAFTS

    agent = llm.ScriptedClient(unavailable_once)
    app.dependency_overrides[llm.get_llm_client] = lambda: agent
    teacher = Teacher(browser, "ms-farouk")
    await teacher.sign_in()

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.lesson_id and drafted.asked == 2 and drafted.reason == ""
    said = [m["text"] for m in (await thread_of(browser))["messages"] if m["role"] == "teacher"]
    assert said == [PART_ONE.words, NUDGE]

    agent_replies(app)  # no replies left: every message is answered 503
    never = await teacher.draft(PART_ONE, TEXTS)
    assert never.lesson_id is None and never.asked == 3
    assert "did not draft" in never.reason and "3 of them got no answer" in never.reason


@pytest.mark.parametrize(
    "written",
    [{**DRAFT, "subject": "mathematics"}, REWORDED],
    ids=["rewritten", "one question reworded"],
)
async def test_a_draft_written_into_an_approved_lesson_is_a_change_to_it(app, browser, written):
    """Every new teacher has the approved sample lesson, and PART_ONE's words name it by its
    title, so the agent is shown it even after a new lesson is begun. A brief that keeps its
    subject is written into it as a new version, not as a new lesson: the draft is that
    version, the reason says so, and it approves and runs like any other. A new version says
    so even when nothing the list shows of the lesson has changed."""
    agent_replies(app, {**DRAFTS, "brief": written})
    teacher = Teacher(browser, "ms-haddad")
    await teacher.sign_in()
    class_id, _ = await teacher.make_class("9S", 2)
    [sample] = await lessons_of(browser)

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.reason == f"written as a change to {sample['title']}"
    assert drafted.lesson_id != sample["lesson_id"] and drafted.asked == 1
    [changed] = await lessons_of(browser)
    assert (changed["lesson_id"], changed["plan_id"]) == (drafted.lesson_id, sample["plan_id"])
    await teacher.approve(drafted.lesson_id)
    assert uuid.UUID(await teacher.run(drafted.lesson_id, class_id))


async def test_an_unapproved_draft_written_over_is_a_change_to_it_not_a_failure(app, browser):
    """A draft left unapproved (one that could not be approved, say) can be named by the next
    lesson's words and written over where it is, keeping its id. That is a change to it, not a
    lesson the agent did not draft."""
    first = brief("Percentages of amounts", 13, ["percentages"])
    rewritten = brief("Percentages: sale prices", 13, ["percentages"])
    agent_replies(
        app,
        {"reply": "Here it is.", "show": "lesson", "brief": first},
        {"reply": "Changed it.", "show": "lesson", "brief": rewritten},
    )
    teacher = Teacher(browser, "mr-brennan")
    await teacher.sign_in()

    earlier = await teacher.draft(GROUP_LESSONS["A"][0], TEXTS)
    assert earlier.lesson_id and earlier.reason == ""
    # The follow-on lesson's words name the first one: "percentages of amounts again".
    drafted = await teacher.draft(GROUP_LESSONS["A"][2], TEXTS)
    assert (drafted.lesson_id, drafted.asked) == (earlier.lesson_id, 1)
    assert drafted.reason == "written as a change to Percentages of amounts"


@pytest.mark.parametrize(
    ("shown", "needs"),
    [
        ({"show": "lesson"}, "it needs what counts as done for step 2"),
        ({}, "the platform says something is still missing"),
    ],
    ids=["on screen", "not on screen"],
)
async def test_a_draft_that_cannot_be_approved_yet_counts_as_drafted_and_says_why(
    app, browser, shown, needs
):
    """A draft with steps is drafted, approvable or not. One that can't be approved yet says
    what it needs, as its card says when it is on screen, so the run can record it as not
    runnable and carry on; pressing Approve says it too."""
    agent_replies(app, {"reply": "Here it is.", **shown, "brief": NOT_READY})
    teacher = Teacher(browser, "ms-oduya")
    await teacher.sign_in()

    drafted = await teacher.draft(PART_ONE, TEXTS)
    assert drafted.lesson_id and drafted.asked == 1
    assert drafted.reason == f"drafted, but it can't be approved yet: {needs}"
    with pytest.raises(NotDone) as refused:
        await teacher.approve(drafted.lesson_id)
    assert refused.value.status == 422
    assert "what counts as done for step 2" in refused.value.detail


async def test_a_platform_failure_while_drafting_is_recorded_not_raised(app, browser):
    """Whatever goes wrong on the platform's side while a lesson is drafted, the lesson comes
    back as not drafted with the reason, never as an exception, so the run can carry on. The
    reason gives the status, or the kind of failure when nothing came back, and nothing the
    platform sent."""
    agent_replies(app)
    teacher = Teacher(browser, "mr-kwame")
    await teacher.sign_in()
    too_long = LessonPlan("long", "maths", 14, "Solve it. " * 700)
    refused = await teacher.draft(too_long, TEXTS)
    assert (refused.lesson_id, refused.asked) == (None, 1)
    assert "422" in refused.reason and "Solve it" not in refused.reason

    slow = NoAnswerTo(app, "/api/teacher/thread/messages")
    async with httpx.AsyncClient(transport=slow, base_url="http://test") as client:
        teacher = Teacher(client, "mr-kwame")
        await teacher.sign_in()
        unanswered = await teacher.draft(PART_ONE, TEXTS)
    assert (unanswered.lesson_id, unanswered.asked) == (None, 1)
    assert "ReadTimeout" in unanswered.reason


async def test_attachments_go_up_first_and_an_empty_lesson_is_not_taken_for_a_draft(
    app, browser, tmp_path
):
    """A file sent before anything is drafted goes to a new, empty lesson, which comes into
    focus as a draft with nothing in it. That is not the agent drafting: the teacher still
    nudges, and the draft is the one the agent then writes, with the files on it."""
    (tmp_path / "notes.txt").write_text("Collect the x terms on one side first.\n")
    # The worksheet as written without python-docx: the same name, another ending.
    (tmp_path / "worksheet.md").write_text("# Equations\n\n1. Solve 5x + 3 = 2x + 18.\n")
    (tmp_path / "marks.csv").write_text("pupil,mark\n1,7\n")
    # Words that name none of the teacher's lessons (the sample's title is about equations
    # with the unknown on both sides), so the lesson in focus is the one the files went to.
    words = (
        "I've attached our worksheet, some notes and last week's marks. Please draft a maths "
        "lesson from them for my 14 year olds on solving equations with brackets, 40 minutes. "
        "By the end they should be able to solve 2(x + 3) = 4x - 2."
    )
    plan = LessonPlan(
        "with-files", "maths", 14, words, attachments=["notes.txt", "worksheet.docx", "marks.csv"]
    )
    agent_replies(app, ASKS, DRAFTS)
    teacher = Teacher(browser, "mr-novak")
    await teacher.sign_in()

    # A file that is in neither form is the run's own mistake: nothing is sent at all.
    missing = LessonPlan("lost", "maths", 14, words, attachments=["lost.txt"])
    with pytest.raises(FileNotFoundError):
        await teacher.draft(missing, tmp_path)
    assert teacher.events == [] and (await thread_of(browser))["messages"] == []

    drafted = await teacher.draft(plan, tmp_path)
    assert drafted.asked == 2 and drafted.reason == ""
    # Each upload is logged, the one the platform refused too, and the lesson goes on.
    assert teacher.events == [
        {"what": "upload", "status": 201, "file": "notes.txt"},
        {"what": "upload", "status": 201, "file": "worksheet.md"},
        {"what": "upload", "status": 415, "file": "marks.csv"},
    ]
    lessons = (await browser.get("/api/teacher/thread/lessons")).json()["lessons"]
    [made] = [lesson for lesson in lessons if lesson["lesson_id"] == drafted.lesson_id]
    assert made["status"] == "draft" and made["steps"] == 4
    card = (await thread_of(browser))["showing"]
    assert card["lesson_id"] == drafted.lesson_id
    assert [m["filename"] for m in card["materials"]] == ["notes.txt", "worksheet.md"]


async def test_the_teachers_buttons_answer_or_say_why_not(app, browser):
    agent_replies(app, OPENS, {"reply": "Nobody needs you yet.", "show": "class"})
    teacher = Teacher(browser, "mr-adeyemi")
    await teacher.sign_in()
    class_id, seats = await teacher.make_class("9S", 2)
    # The sample lesson every new teacher has, approved already.
    [sample] = (await browser.get("/api/teacher/thread/lessons")).json()["lessons"]

    with pytest.raises(NotDone) as refused:
        await teacher.approve(sample["lesson_id"])
    assert refused.value.status == 409
    assert refused.value.detail == "This version is already approved."
    # Worked out first, so that a failure could never print the cookie.
    leaked = browser.cookies["pact_teacher"] in str(refused.value)
    assert not leaked

    shown = await teacher.preview(sample["lesson_id"])
    assert shown["messages"][-1]["text"].startswith("How step 1 would open for a student")
    filed = await teacher.set_unit(sample["lesson_id"], "Equations")
    assert filed["showing"]["unit"] == "Equations"

    # Ids go as strings, whatever they were given as.
    session_id = await teacher.run(uuid.UUID(sample["lesson_id"]), uuid.UUID(class_id))
    card, _ = await teacher.class_view()
    assert (card["type"], card["session_id"]) == ("class", session_id)
    assert len(card["students"]) == len(seats)

    reply, seconds = await teacher.ask("Who needs me right now?")
    assert reply == "Nobody needs you yet."
    assert isinstance(seconds, float) and seconds >= 0


async def test_letting_the_tutor_adapt_keeps_every_other_setting(browser):
    teacher = Teacher(browser, "ms-kowalski")
    await teacher.sign_in()
    chosen = {
        "remember": False,
        "forget_after_days": 30,
        "written_lines": False,
        "recent_lines": 4,
        "harder_questions": True,
    }
    await teacher.settings(**chosen)

    assert await teacher.let_adapt() == {**chosen, "adapt_to_student": True}
    stored = (await browser.get("/api/research/memory")).json()["settings"]
    assert stored == {**chosen, "adapt_to_student": True}
    # A setting the platform does not have is refused here, not dropped without a word.
    with pytest.raises(TypeError):
        await teacher.settings(adapt_to_pupil=True)
    # Forgetting what is remembered of the pupils leaves the settings as they are.
    assert await teacher.forget_all() is None
    after = (await browser.get("/api/research/memory")).json()
    assert after == {"settings": stored, "students": 0}
