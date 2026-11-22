"""The teacher of the school day: signs in, makes a class of pupils with join codes, describes
each lesson to the class agent in words until it drafts it, approves and runs it, presses the
teacher's buttons, reads the class view, asks the agent questions and changes their own
settings. All of it over HTTP, the way the teacher's browser does it, with one client (one
cookie jar) per teacher. A cookie is never printed, logged or put in a message.

Drafting is where a run can stall: the agent may keep asking questions instead of drafting.
So the teacher types the lesson's words, then nudges at most twice ("That's everything,
please draft it."), and with still no draft the lesson is recorded as not drafted, with a
plain reason, so that the run can carry on with the rest.

What the agent drafted is read from the teacher's list of lessons, which shows the newest
version of each lesson, against the list as it was before they asked. A draft with steps in it
is a new lesson when its lesson was not on the list with steps before. On a lesson that was, it
is a change to that lesson: a new version of it (a change to an approved lesson makes one), or
the same draft with its title, subject, steps, length or readiness changed. A change is still
drafted, and its reason names the lesson it changed: the words can name one of the teacher's
lessons (every new teacher has the approved sample lesson), and the agent then writes into that
one. A draft that can't be approved yet is drafted too, and its reason says what it needs. A
change the list can't see (the same draft, nothing it shows changed) is not found. What is in
focus does not say any of this: a file sent before anything is drafted goes to a new, empty
lesson, which comes into focus as a draft at once, and a draft the agent does not put on screen
leaves nothing in focus.

draft() never raises for the platform. Whatever goes wrong there, the lesson comes back as not
drafted, with the status, or the kind of failure when nothing came back, and never anything
the platform sent, so that the run can record it and carry on. While drafting, an upload's
status, whatever it is, is logged and the lesson goes on, and a message the agent could not
answer (503) counts as asked: the platform keeps it, so the teacher's next message is their
trying again. Every other request the platform answers with an error raises NotDone, with the
status and what the platform said.

The client's timeout must allow for the class agent, whose reply can take a minute or more.
"""

import json
import mimetypes
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from bench.school.lessons import LessonPlan

# The password the run's teachers type. Demo sign-in never checks it.
PASSWORD = "school-day"
# What the teacher says while the agent asks instead of drafting, and how many times at most.
NUDGE = "That's everything, please draft it."
NUDGES = 2
# The platform's answer when the class agent could not answer a message.
UNAVAILABLE = 503
# What the teacher's list of lessons shows of a lesson that a change to it can alter.
SEEN = ("title", "subject", "steps", "duration_minutes", "ready")

THREAD = "/api/teacher/thread"
MESSAGES = f"{THREAD}/messages"
ACTIONS = f"{THREAD}/actions"
MATERIALS = f"{THREAD}/materials"
LESSONS = f"{THREAD}/lessons"
MEMORY = "/api/research/memory"


@dataclass
class Seat:
    """A pupil of a class the teacher made, and the join code they sign in with."""

    student_id: str
    pseudonym: str
    # A code signs its pupil in, so a seat printed in a log line leaves it out.
    code: str = field(repr=False)


@dataclass
class Drafted:
    """How drafting a lesson went: the draft's id, or None when it was not drafted; how many
    messages the teacher sent the agent (the words and any nudges); and, in plain words, why
    there is no draft, or what to know of the one there is (that it is a change to a lesson
    the teacher had, or that it can't be approved yet). A new draft ready to approve has no
    reason."""

    lesson_id: str | None
    asked: int
    reason: str = ""


class NotDone(Exception):
    """The platform answered a request with an error. `status` is the HTTP status and `detail`
    what the platform said. The message names the request too, and never holds a cookie."""

    def __init__(self, request: str, status: int, detail: str) -> None:
        super().__init__(f"{request} answered {status}: {detail}")
        self.status = status
        self.detail = detail


class Teacher:
    """One teacher of the run, signed in through `client`, which holds their cookie and no one
    else's. `events` is what the teacher logs: one {"what": "upload", "status", "file"} for
    each file they send."""

    def __init__(self, client: httpx.AsyncClient, name: str) -> None:
        self.client = client
        self.name = name
        self.events: list[dict] = []

    async def sign_in(self) -> None:
        """Demo sign-in under the teacher's name. The first time makes the teacher, with a class
        of their own and the sample lesson."""
        teacher = {"role": "teacher", "username": self.name, "password": PASSWORD}
        await self._call("POST", "/api/auth/demo", json=teacher)

    async def let_adapt(self) -> dict:
        """Lets the tutor pitch each step for the pupil in front of it, and keeps every other
        setting as it was."""
        return await self.settings(adapt_to_student=True)

    async def settings(self, **changes: Any) -> dict:
        """Changes these of the teacher's settings and keeps the rest as they were: the platform
        takes them all at once, so they are read first. Returns them as saved. A name the
        platform has no setting for raises TypeError, since the platform would drop it without
        a word."""
        now = (await self._call("GET", MEMORY))["settings"]
        unknown = sorted(set(changes) - set(now))
        if unknown:
            raise TypeError(
                f"There is no setting called {', '.join(unknown)}: the settings are "
                f"{', '.join(now)}."
            )
        return (await self._call("PUT", MEMORY, json={**now, **changes}))["settings"]

    async def forget_all(self) -> None:
        """Deletes what is remembered of this teacher's pupils. The settings stay as they are."""
        await self._call("DELETE", MEMORY)

    async def make_class(self, label: str, size: int) -> tuple[str, list[Seat]]:
        """A class of `size` pupils, named by the platform, and a join code for each: the
        class's id and a seat for each pupil."""
        made = await self._call(
            "POST", "/api/teacher/classes", json={"label": label, "students": size}
        )
        class_id = str(made["id"])
        codes = await self._call("POST", f"/api/teacher/classes/{class_id}/join-codes")
        return class_id, [Seat(str(c["student_id"]), c["pseudonym"], c["code"]) for c in codes]

    async def draft(self, plan: LessonPlan, texts: Path) -> Drafted:
        """Asks the class agent for the lesson the way a teacher does: a new lesson, then each of
        its attachments from `texts`, then its words. While the agent has drafted nothing, the
        teacher nudges, twice at most. With still no draft, the result has no lesson and says
        why. It never raises for the platform (see above).

        An attachment `texts` does not hold goes up under another ending when the folder has a
        file with the same stem (worksheet.md for worksheet.docx). With neither, the run has
        made a mistake: FileNotFoundError, before anything is sent."""
        files = [_attachment(texts, name) for name in plan.attachments]
        asked = unanswered = 0
        step = "the list of lessons"
        try:
            had = await self._with_steps()
            step = "the new lesson button"
            await self.act("new_lesson")
            for path in files:
                step = f"the upload of {path.name}"
                await self._upload(path)
            for text in (plan.words, *[NUDGE] * NUDGES):
                step = f"nudge {asked}" if asked else "the lesson's words"
                asked += 1
                reply = await self.client.post(MESSAGES, json={"text": text})
                if reply.status_code == UNAVAILABLE:
                    unanswered += 1
                    continue
                thread = _answer(reply)
                step = "the list of lessons"
                written = _written(had, await self._with_steps(), thread)
                if written is not None:
                    lesson_id, reason = written
                    return Drafted(lesson_id, asked, reason)
        except NotDone as refused:
            said = f"the platform answered {refused.status} to {step}"
            return Drafted(None, asked, f"The lesson was not drafted: {said}.")
        except httpx.HTTPError as failed:
            said = f"{step} got no answer from the platform ({type(failed).__name__})"
            return Drafted(None, asked, f"The lesson was not drafted: {said}.")
        reason = (
            f"The class agent did not draft the lesson: after {asked} messages from the teacher "
            f"(the lesson's words and {asked - 1} nudges), their lessons show no new draft and "
            "no change to one"
        )
        if unanswered:
            reason += f"; {unanswered} of them got no answer, as the agent was unavailable"
        return Drafted(None, asked, reason + ".")

    async def approve(self, lesson_id: str | uuid.UUID) -> dict:
        """Approves the draft, so that it can be run. Returns the thread."""
        return await self.act("approve", lesson_id=lesson_id)

    async def run(self, lesson_id: str | uuid.UUID, class_id: str | uuid.UUID) -> str:
        """Starts the approved lesson with the class now; the id of the run (its session)."""
        thread = await self.act("run", lesson_id=lesson_id, class_id=class_id)
        return thread["showing"]["session_id"]

    async def preview(self, lesson_id: str | uuid.UUID) -> dict:
        """How step 1 would open for a pupil, which the platform writes into the thread.
        Returns the thread."""
        return await self.act("preview_lesson", lesson_id=lesson_id)

    async def set_unit(self, lesson_id: str | uuid.UUID, text: str) -> dict:
        """Puts the lesson in the unit called `text`. Returns the thread."""
        return await self.act("set_unit", lesson_id=lesson_id, text=text)

    async def act(self, action: str, **fields: Any) -> dict:
        """Presses one of the teacher's buttons, with its fields, ids as strings. Returns the
        thread as the platform sends it back; a press it refuses raises NotDone, with the status
        and what it said."""
        body = {"action": action, **{name: _sent(name, v) for name, v in fields.items()}}
        return await self._call("POST", ACTIONS, json=body)

    async def ask(self, text: str) -> tuple[str, float]:
        """Says `text` to the class agent: its reply, and the seconds it took."""
        started = time.perf_counter()
        thread = await self._call("POST", MESSAGES, json={"text": text})
        return _agent_said(thread), time.perf_counter() - started

    async def class_view(self) -> tuple[dict, float]:
        """Reads the thread as the teacher's screen does: the card on screen (empty when there
        is none), and the seconds it took."""
        started = time.perf_counter()
        thread = await self._call("GET", THREAD)
        return thread.get("showing") or {}, time.perf_counter() - started

    async def _call(self, method: str, path: str, **sent: Any) -> Any:
        return _answer(await self.client.request(method, path, **sent))

    async def _upload(self, path: Path) -> None:
        """Sends one file as the browser does, with nothing beside it: the platform puts it on
        the lesson in focus, or on a new lesson when none is. Its status is logged."""
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        upload = {"file": (path.name, path.read_bytes(), kind)}
        reply = await self.client.post(MATERIALS, files=upload)
        self.events.append({"what": "upload", "status": reply.status_code, "file": path.name})

    async def _with_steps(self) -> dict[str, dict]:
        """The teacher's lessons with steps in them, by plan (a lesson and all its versions),
        newest first, each as their list of lessons shows its newest version. The list writes
        nothing. A lesson with no steps is an empty one, such as the one a file goes to before
        anything is drafted."""
        listed = (await self._call("GET", LESSONS))["lessons"]
        return {x["plan_id"]: x for x in listed if x["steps"]}


def _attachment(folder: Path, name: str) -> Path:
    """The file to send for an attachment the lesson names: that file in `folder`, or else the
    one there with the same stem (make_files writes worksheet.md when it can't write
    worksheet.docx)."""
    named = folder / name
    if named.is_file():
        return named
    stem = Path(name).stem
    others = sorted(p for p in folder.glob("*") if p.is_file() and p.stem == stem)
    if not others:
        raise FileNotFoundError(
            f"The lesson attaches {name}, and {folder} has no file of that name with any ending."
        )
    return others[0]


def _written(had: dict[str, dict], now: dict[str, dict], thread: dict) -> tuple[str, str] | None:
    """The draft the agent has written, as its id and its reason, from the teacher's lessons
    with steps before they asked (`had`) and now; None when the list shows none. A draft is new
    when its lesson had no steps before. On a lesson that had, it is a change to that lesson
    when the newest version is another one, or when the list shows it changed (SEEN)."""
    for plan_id, lesson in now.items():
        if lesson["status"] != "draft":
            continue
        before = had.get(plan_id)
        if before is None:
            change = ""
        elif lesson["lesson_id"] != before["lesson_id"] or _seen(lesson) != _seen(before):
            change = f"written as a change to {before['title']}"
        else:
            continue
        if lesson["ready"]:
            return lesson["lesson_id"], change
        needs = _needs(thread, lesson["lesson_id"])
        return lesson["lesson_id"], f"{change or 'drafted'}, but it can't be approved yet: {needs}"
    return None


def _seen(lesson: dict) -> tuple:
    return tuple(lesson.get(name) for name in SEEN)


def _needs(thread: dict, lesson_id: str) -> str:
    """What a draft needs before it can be approved, as its card says when the agent put it on
    screen. The list of lessons only says whether it is ready."""
    card = thread.get("showing") or {}
    if card.get("type") == "lesson" and card.get("lesson_id") == lesson_id and card.get("missing"):
        return "it needs " + ", ".join(card["missing"])
    return "the platform says something is still missing"


def _sent(name: str, value: Any) -> Any:
    """A button's field as the browser sends it: an id (a field named for one, or a UUID) as a
    string."""
    if value is not None and (name.endswith("_id") or isinstance(value, uuid.UUID)):
        return str(value)
    return value


def _agent_said(thread: dict) -> str:
    """The agent's newest message in the thread. Events can follow it: an approval it was asked
    for, say, or why it could not be done."""
    said = [m["text"] for m in thread["messages"] if m["role"] == "agent"]
    return said[-1] if said else ""


def _answer(reply: httpx.Response) -> Any:
    """The platform's answer as data, or NotDone when it is an error."""
    if reply.is_success:
        return reply.json() if reply.content else None
    request = f"{reply.request.method} {reply.request.url.path}"
    raise NotDone(request, reply.status_code, _detail(reply))


def _detail(reply: httpx.Response) -> str:
    """What the platform said about an error: its detail (a list of what failed validation, as
    JSON), or else the start of what it sent."""
    try:
        said = reply.json()
    except ValueError:
        return reply.text[:500]
    detail = said.get("detail", said) if isinstance(said, dict) else said
    return detail if isinstance(detail, str) else json.dumps(detail)[:500]
