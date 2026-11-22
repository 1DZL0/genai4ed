# Settings tab, planning by talking and the lesson card: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

Written 18 November 2026. Diesel gave the word to build on 17 November and put three points
off (see the spec, "Put off by Diesel"). This plan covers stages 2 to 4 of the spec's order of
work. Stages 5 and 6 (the tutor, the record and the teacher's views) get their own plan. Going
live and the demo set-up are a runbook, and every live step needs Diesel's word at that moment.

**Goal:** A teacher gets a Settings page of on/off switches, can plan a lesson by talking with
the boxes hidden, and sees on the lesson card which objective each step serves, what counts as
meeting it, and an easier step and a deeper question beside the baseline.

**Architecture:** One new table holds a teacher's switches about planning and questions; it is
read through one small module and served by one small router. A teacher who has set nothing has
no row and gets today's platform, prompts included, byte for byte. Each planning switch is a
prompt variant with its own version label and its own bench run. The lesson card stays one JSON
`brief`; the new step fields are hidden from the agent's reply shape unless a switch is on.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Postgres 18, pytest; Next.js 16.4.6,
React 19.3, Tailwind v4, SWR. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-17-personal-questions-design.md`

## Global Constraints

- Test copy only: database `genai4ed_memory`, API on 127.0.0.1:8010, website on 127.0.0.1:3002.
  Never ports 3000 or 8000, never the database `genai4ed`.
- Any backend command left on default settings works on the live database. Every command names
  its database. The copy's URL is built by command substitution and never written down (see
  "Running things on the test copy"). No password, key or `.env` value goes in a file or reply.
- Nothing is committed, pushed, migrated on live or rebuilt on live without Diesel's word. So a
  task ends with a suite run and a ledger line, not a commit.
- A teacher who has set nothing gets today's platform. The teacher prompt keeps its version,
  `teacher-v26-710d809c`, pinned by a test.
- No second model call to check a question the tutor writes (Diesel).
- Before any paid run, check the key's balance (numbers only) and stop to ask below $15. Keep
  each run as small as its change allows.
- A switch is on the Settings page only once it does something, and on the live site only after
  its prompt has had its bench run.
- Backend changes are written test first. The whole suite (`uv run pytest -q` from `backend/`)
  is green before a task is called done.
- Words on screen: plain, no long dashes, ages not year groups. In code, "ladder" and "rung"
  already mean the order of help (`LADDER`, `off_ladder`, `rung_permitted`): the new parts are
  called `card_extras`, `easier`, `deeper`.
- Test accounts only (`review-three-24515`, `layout-look-test-teacher`, pupils `2ZXWK`, `BD2Z6`,
  `T23K8` on the copy). Never teacher-1/2/3, the professor's, a colleague's or Diesel's accounts.
- Prompt rules (Diesel): prefer examples and positive instructions; every rule traces to a
  failure seen in a run, and rules that do not are cut.

## Review Focus

1. **A lesson written before this change.** A stored brief whose steps have no `objective`,
   `easier` or `deeper` reads, shows and runs exactly as before. Test in Task 7.
2. **Objectives change under the steps.** When the teacher's objectives are reordered or one is
   removed, a step never ends up pointing at a different objective: a number carried over by the
   server is dropped unless the objectives are word for word what they were. Test in Task 7.
3. **A first message that already says everything.** With ask-first on, a teacher who gives the
   objectives, the age and the length in one message gets a draft at once, not questions. Test
   in Task 5.
4. **Switching on and then off again.** A teacher who turned every switch back off is sent
   today's prompt and their turns carry today's version. Test in Task 4.
5. **Two things saving on one page.** The deeper-question row and the memory panel write the
   same stored row. Saving the memory panel never puts back an old value of the deeper switch.
   No frontend test runner exists, so this is checked by hand in the browser in Task 2, and the
   steps are written there.

## Decisions already made

Diesel's are in the spec. These are mine, made while planning, for Diesel to check.

1. The switches get their own table, `teaching_settings`, with all five columns in one
   migration: `ask_first`, `card_extras`, `quick_choices`, `personal_examples`, `easier_step`.
   Fewer migrations on live. A column whose switch does nothing yet is simply not shown.
2. Defaults in code: everything off except `quick_choices` (the boxes are shown). What a newly
   made account starts with is put off, so it is chosen when the account is made.
3. The route is `/api/teacher/settings` with a read and a merging change (`PATCH`). A change
   carries only the switch that moved, so two quick clicks cannot undo each other.
4. `harder_questions` stays where it is stored (`memory_settings`) and is still written through
   the memory endpoint. Only the row moves on screen, to "Questions for each student".
5. Tick rows save at once and say "Saved". The memory panel keeps its Save button because it
   has number fields.
6. With the boxes hidden, the in-chat activity headings are hidden too, and a teacher says the
   kind of activity in words.
7. Hiding the boxes is not only a screen change: the agent's prompt points at "the settings
   under the box" in three places and the "Where this lesson stands" block talks about the
   activity box. Whether the agent then sends teachers to a control they cannot see is measured
   first (Task 6). A line is added to the prompt only if the run shows it happening.
8. The follow-up button keeps drafting at once, even with ask-first on.
9. A step names one objective by its place in the list (1 for the first). The agent rewrites the
   whole brief each time, so it keeps the numbers right; the server only clears a number that
   points past the end of the list.
10. The words under the typing box become "Tutor settings for this lesson" and its link
    "this lesson's settings", so they are not confused with the Settings page.
11. Built inline in one session, with one independent review at the end. Not confirmed by
    Diesel, who said to start building.

## Running things on the test copy

From `backend/`, the copy's URL is built from the app's own settings with only the database
name changed, and is never printed:

```bash
COPY_URL() { uv run python -c 'from app.config import get_settings
from sqlalchemy.engine import make_url
u = make_url(get_settings().database_url).set(database="genai4ed_memory")
print(u.render_as_string(hide_password=False))'; }
DATABASE_URL="$(COPY_URL)" uv run alembic upgrade head
DATABASE_URL="$(COPY_URL)" uv run alembic check
DATABASE_URL="$(COPY_URL)" COOKIE_SECURE=false DEMO_SIGN_IN=true \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
```

The website: from `frontend/`, `API_INTERNAL_URL=http://127.0.0.1:8010 npm run build`, copy
`.next/standalone` to a scratch folder with `.next/static` inside its `.next`, then
`PORT=3002 HOSTNAME=127.0.0.1 node server.js`. Afterwards build once more without
`API_INTERNAL_URL`, because the default points at the live API. Sign in on the copy with
`POST /api/auth/demo` and `{role, username, password}`.

The pytest suite runs on `genai4ed_test` and makes its tables from the models, so nothing in
it checks a migration against its model. That is what `alembic check` on the copy is for.

## File map

| File | What it is for |
| --- | --- |
| `backend/app/models.py` | new `TeachingSettings`, after `MemorySettings` |
| `backend/app/agent/teaching_settings.py` | new: `Settings`, `of`, `save` |
| `backend/app/routers/teaching.py` | new: read and change the switches |
| `backend/alembic/versions/a3b4c5d6e7f8_teaching_settings.py` | new table |
| `backend/tests/test_teaching_settings.py` | new |
| `backend/app/agent/teacher_prompt.py` | ask-first text beside `TALK`; `system()` |
| `backend/app/agent/thread.py` | variants: system text, reply shape, version, the held rule |
| `backend/app/agent/brief.py` (where `Step` and `LessonBrief` live) | new step fields |
| `backend/app/agent/cards.py` | the card's new parts |
| `backend/bench/teacher_cases.py`, `teacher_run.py` | cases that set a teacher's switches |
| `frontend/lib/api.ts` | `TeachingSettings`, `teachingApi` |
| `frontend/components/teaching-settings.tsx` | new: the two panels of tick rows |
| `frontend/app/teacher/settings/page.tsx` | new: the Settings page |
| `frontend/components/memory-settings.tsx` | loses the deeper-question row |
| `frontend/components/app-header.tsx` | the fifth rail button |
| `frontend/app/teacher/page.tsx`, `components/quick-choices.tsx` | boxes behind the switch |
| `frontend/app/research/page.tsx`, `components/research-view.tsx` | memory panel moved out |
| `frontend/components/cards/lesson.tsx` | objective, "Met when", the extras |

---

## Stage 2: the Settings tab

### Task 1: The switches, stored and served

**Files:**
- Create: `backend/tests/test_teaching_settings.py`, `backend/app/agent/teaching_settings.py`,
  `backend/app/routers/teaching.py`,
  `backend/alembic/versions/a3b4c5d6e7f8_teaching_settings.py`
- Modify: `backend/app/models.py` (after `MemorySettings`), `backend/app/main.py`

**Interfaces:**
- Produces: `teaching_settings.Settings` with `ask_first: bool = False`,
  `card_extras: bool = False`, `quick_choices: bool = True`, `personal_examples: bool = False`,
  `easier_step: bool = False`.
- Produces: `async def of(db: AsyncSession, teacher_id: uuid.UUID) -> Settings` and
  `async def save(db: AsyncSession, teacher_id: uuid.UUID, settings: Settings) -> None`
  (the caller commits).
- Produces: `GET /api/teacher/settings` returns the five switches. `PATCH /api/teacher/settings`
  takes any of them as `true` or `false`, changes only those, and returns all five. Unknown
  name or a value that is not a boolean: 422. Not signed in: 401. A student: 403.

- [ ] **Step 1: Write the tests.** `SETTINGS = "/api/teacher/settings"` and
  `AS_IT_WAS = {"ask_first": False, "card_extras": False, "quick_choices": True,
  "personal_examples": False, "easier_step": False}`, with fixtures `client`, `classroom`, `db`:
  - `test_a_teacher_who_set_nothing_has_the_platform_as_it_always_was`: GET is `AS_IT_WAS`, and
    the table still has no row.
  - `test_what_a_teacher_switches_is_what_they_read_back`: PATCH `{"ask_first": True}` then
    `{"quick_choices": False}`; each answer and a GET equal `AS_IT_WAS` with both changed.
  - `test_a_change_that_names_nothing_changes_nothing`: PATCH `{}` is 200 and `AS_IT_WAS`.
  - `test_a_value_that_is_not_on_or_off_is_refused`: `{"ask_first": "maybe"}`,
    `{"ask_first": 1}` and `{"master": True}` are each 422, and GET is still `AS_IT_WAS`.
  - `test_only_a_teacher_has_these_switches`: a student gets 403 on GET and PATCH; with no
    header both are 401.
  - `test_one_teachers_switches_leave_another_teachers_alone`: `classroom.teacher` switches
    `ask_first` on; `classroom.other_teacher` still reads `AS_IT_WAS`.
- [ ] **Step 2: Run them and see them fail** (`uv run pytest -q tests/test_teaching_settings.py`).
  Expected: every test fails on 404, because the route does not exist.
- [ ] **Step 3: `TeachingSettings` in `models.py`**, `Base, TimestampMixin`, table
  `teaching_settings`, key `teacher_id` to `users.id` with `ondelete="CASCADE"`. A docstring and
  a comment above each column (the schema view test reads both).
- [ ] **Step 4: `teaching_settings.py`**, the shape of `memory_settings.py`'s first three parts.
- [ ] **Step 5: `routers/teaching.py`** with `router = APIRouter(prefix="/api/teacher/settings",
  tags=["settings"])`, a `Changes` model (each switch `StrictBool | None = None`,
  `extra="forbid"`), merged with `model_dump(exclude_none=True)`. Not named `settings.py`:
  `create_app` has a local of that name. Include it in `main.py`.
- [ ] **Step 6: The migration**, `down_revision = "f2a3b4c5d6e7"`, in the style of
  `e1f2a3b4c5d6_memory_settings.py` (no server defaults on the switches).
- [ ] **Step 7: Run the file, then the whole suite.** Expected: all green.
- [ ] **Step 8: On the copy:** `alembic upgrade head`, then `alembic check`. Expected: one
  operation only, the older `modify_type` note on `agent_turns.usage` (a JSON type, there
  before this work), and nothing about `teaching_settings`.
- [ ] **Step 9: Ledger line.**

### Task 2: The Settings page and the rail button

**Files:**
- Create: `frontend/components/teaching-settings.tsx`, `frontend/app/teacher/settings/page.tsx`
- Modify: `frontend/lib/api.ts`, `frontend/components/memory-settings.tsx`,
  `frontend/components/app-header.tsx`

**Interfaces:**
- Consumes: Task 1's two routes; the memory endpoint as it is (`researchApi.memory`,
  `researchApi.saveMemory`, SWR key `["research-memory", researchKey]`).
- Produces: `type TeachingSettings` (the five booleans), `teachingApi.settings()` and
  `teachingApi.change(changes: Partial<TeachingSettings>)`, SWR key `"teaching-settings"`;
  `PlanningPanel()` and `QuestionsPanel({ researchKey })`.

- [ ] **Step 1: `api.ts`:** the type and the two calls with `request<T>`.
- [ ] **Step 2: `teaching-settings.tsx`:** a tick row in the memory panel's look (title, one
  grey line) that saves on change and shows "Saved" beside the panel title. Rows now:
  - Planning a lesson: **Show the Activity and Tutor choices by the typing box**. "The
    Activity line above where you type and the Tutor line under it. Switched off, you say what
    you want in words." (The names a teacher sees on the screen, not "quick-choice boxes".)
  - Questions for each student: **Ask a deeper question when a student gets a step right first
    time**. "One extra question that asks why or asks them to compare. It is tagged in the
    record and does not change the mark." It saves the memory row with only that value changed.
- [ ] **Step 3: `memory-settings.tsx`:** the deeper-question row goes. On save the panel sends
  the server's own `harder_questions`, never the one it loaded with.
- [ ] **Step 4: The page** at `/teacher/settings`, three panels in the spec's order, the memory
  panel third with its delete button. Titled "Settings", one line under it: "These hold for
  every lesson of yours."
- [ ] **Step 5: The rail:** a fifth button, Settings, after Research. Check the wrap at phone
  width (400px).
- [ ] **Step 6: `npm run lint` and `npm run build`.** Expected: no errors.
- [ ] **Step 7: In the browser on the copy** (rebuild against 8010, restart the API first):
  tick and untick each row and reload (the value holds); change the deeper row, then press Save
  in the memory panel without reloading, then reload (the deeper row is as it was left).
- [ ] **Step 8: Ledger line.**

### Task 3: The boxes behind their switch, and the Research page tidied

**Files:**
- Modify: `frontend/app/teacher/page.tsx`, `frontend/components/quick-choices.tsx`,
  `frontend/components/teaching-settings.tsx`, `frontend/components/chat.tsx`,
  `frontend/app/research/page.tsx`, `frontend/components/research-view.tsx`

**Interfaces:**
- Consumes: `teachingApi.settings()`, key `"teaching-settings"`.
- Produces: `useTeachingSettings(signedIn = true)` (asks only when a teacher is signed in) and
  `useBoxesShown(signedIn: boolean): boolean`.

- [ ] **Step 1: The teacher page** reads the switches. Until they arrive it goes by what this
  browser last read (`localStorage`, key `genai4ed.quickChoices.shown`), and shows the boxes in
  a browser that never read them (today's look for the many who never switch). With
  `quick_choices` off: no activity box above the typing box, no tutor settings line, no
  quick-choices panel, no activity headings in the chat, and nothing pressed earlier rides
  along with a message. Nothing stored is removed: a lesson's earlier presses stay in its
  record and on its card.
- [ ] **Step 2: The words** in `quick-choices.tsx`: "Tutor settings for this lesson", link
  "this lesson's settings" (and "hide settings" stays).
- [ ] **Step 3: The Research page:** the memory panel and the sentence "The memory settings are
  the only thing here that changes anything." go; the local `Settings` component is renamed
  `ResearchKey`.
- [ ] **Step 4: Lint, build, and look on the copy** at desktop and phone width, boxes on and
  off, with a lesson that has an activity pressed.
- [ ] **Step 5: Ledger line.**

---

## Stage 3: planning by talking

Read first: `backend/app/agent/teacher_prompt.py`, `thread.py` (`_version`, `_stands`,
`_breaks`, `_system`, `respond`, `_turn`), `backend/app/routers/thread_lessons.py`,
`bench/teacher_cases.py` (`State`, `Case`, `CASES`), `tests/test_teacher_set.py`.

### Task 4: The ask-first text and the versions

**Files:**
- Modify: `backend/app/agent/teacher_prompt.py`, `backend/app/agent/thread.py`
- Test: `backend/tests/test_teacher_variants.py` (new)

**Interfaces:**
- Consumes: `teaching_settings.of`.
- Produces: `teacher_prompt.TALK_ASK_FIRST` (a constant outside `MODULES`, so
  `set(TRACES) == set(MODULES) - {"who"}` stays true) and
  `teacher_prompt.system(*, ask_first: bool = False) -> str`. `SYSTEM` is unchanged, and
  `system()` returns it.
- Produces: in `thread.py`, a small frozen `Variant` (system text, reply model, stands
  sentences, version label) built by `variant(settings: teaching_settings.Settings) -> Variant`.
  With every planning switch off it is today's: `SYSTEM`, `TeacherTurnOut`, `PROMPT_VERSION`.
  Labels: `teacher-v26+ask-<hash8>`, `teacher-v26+extras-<hash8>`,
  `teacher-v26+ask+extras-<hash8>`.
- `respond` reads the teacher's switches once, sends the variant's text as both the start of
  the system prompt and `cache_prefix`, asks for the variant's reply model, and `_turn` records
  the variant's version.

The ask-first text follows the house rules the existing tests pin: worked `Teacher: "` and
`Your reply: "` examples, positive instructions, at most one "never", the "How to talk"
heading, the whole system text under 7000 characters. What it says: for a new lesson, find out
the objectives, the age and the length before drafting; ask two things at most in one reply;
when the teacher says "you decide", offer objectives and wait for a yes; the follow-up button
is the exception and drafts at once. It does not mention "the settings under the box".

- [ ] **Step 1: Tests.**
  - `test_a_teacher_with_every_switch_off_keeps_todays_teacher_prompt`:
    `thread.PROMPT_VERSION == "teacher-v26-710d809c"`; a turn by a teacher with no row sends a
    system prompt that starts with `SYSTEM` and records that version.
  - `test_a_teacher_who_switched_ask_first_off_again_is_back_on_todays_prompt` (Review Focus 4).
  - `test_with_ask_first_on_the_agent_is_sent_the_ask_first_text_under_its_own_version`: the
    system prompt starts with `system(ask_first=True)`; the version starts `teacher-v26+ask-`.
  - `test_the_ask_first_text_keeps_the_house_rules`: length, heading, examples, one "never".
- [ ] **Step 2: See them fail.** **Step 3: Implement.** **Step 4: File, then suite, green.**
- [ ] **Step 5: Ledger line.**

### Task 5: The rule the server holds

**Files:**
- Modify: `backend/app/agent/thread.py` (`_stands`, `_breaks`)
- Test: `backend/tests/test_teacher_variants.py`

**Interfaces:**
- Consumes: Task 4's `Variant`; `lessons.is_empty_draft`.
- Produces: with ask-first on, for a new lesson (`out.new_lesson`, or the teacher asked for a
  new one, or no lesson in focus, or an empty draft in focus) and not the follow-up button, a
  reply whose brief has no objectives, no age or no length is sent back once with "Leave brief
  empty and ask for what is missing, two questions at most." A brief whose `to_check` says the
  objectives were guessed is sent back the same way. What was said so far is in the
  conversation (the last 24 messages); nothing new is stored.

- [ ] **Step 1: Tests** with the scripted client:
  - `test_with_ask_first_on_a_draft_with_no_objectives_is_sent_back_and_nothing_is_saved`
  - `test_with_ask_first_on_a_message_that_says_everything_is_drafted_at_once` (Review Focus 3:
    one model call, the lesson saved)
  - `test_the_follow_up_button_drafts_at_once_even_with_ask_first_on`
  - `test_with_ask_first_off_a_draft_with_no_objectives_goes_through_as_today`
- [ ] **Step 2: See them fail.** **Step 3: Implement.** **Step 4: File, then suite, green.**
- [ ] **Step 5: Ledger line.**

### Task 6: Bench cases for the switches, and the runs

**Files:**
- Modify: `backend/bench/teacher_cases.py`, `backend/bench/teacher_run.py`,
  `backend/bench/teacher_set.py`, `backend/tests/test_teacher_set.py`
- Modify after a clean run: `frontend/components/teaching-settings.tsx` (the row appears)

**Interfaces:**
- Produces: a case can carry its teacher's switches (a field on the case's state), which
  `teacher_run._set_up` saves for the room's teacher before the message is sent.
- Produces: new keys in `RULES`: `ask-first` (no draft until objectives, age and length are
  known), `ask-two` (two questions at most), `offer-objectives` (on "you decide" it offers
  objectives and waits), `no-box-words` (with the boxes hidden the reply does not point at the
  activity box or the settings under it).

- [ ] **Step 1: Cases.** About ten for ask-first (a topic only; objectives only; everything in
  one message; "you decide"; a redraft of a lesson that exists; the follow-up button; a Greek
  message) and about six with the boxes hidden (asks for hints off; asks what kind of activity;
  asks how to change the tutor's rules). Each check names one of the new rules.
- [ ] **Step 2: The suite** (the set's own tests pin that every check names a rule).
- [ ] **Step 3: Balance, then a targeted run** of only the new cases (`--only`), about 16
  replies. Expected: every check passes. A failure is read before anything is changed.
- [ ] **Step 4: Only if `no-box-words` fails:** one line in the "Where this lesson stands"
  block for a teacher with the boxes hidden (there is no activity box and no tutor settings
  line on their screen; a change to the tutor's rules is made by telling you in words). That
  makes a variant with its own label; run the boxes-hidden cases again.
- [ ] **Step 5: Balance, then the full set with ask-first on** (about $1.50). Expected: no case
  that passed with the switch off fails, apart from those the switch is meant to change.
- [ ] **Step 6: The row "Ask me questions before drafting" appears** on the Settings page.
  "The agent finds out your objectives, the age and the length first. Switched off, it drafts
  from whatever you give it."
- [ ] **Step 7: Ledger line** with the run labels and their cost.

---

## Stage 4: the lesson card

Read first: where `Step`, `LessonBrief` and `TeacherTurnOut` are defined, `cards.py`,
`thread._apply_brief` and `_keep_activity`, `frontend/components/cards/lesson.tsx`.

### Task 7: Steps name their objective, and carry an easier step and a deeper question

**Files:**
- Modify: the brief models, `backend/app/agent/thread.py` (`_apply_brief`, the reply models)
- Test: `backend/tests/test_brief_extras.py` (new)

**Interfaces:**
- Produces: `class Extra(BaseModel)` with `question: str` (1 to 600 characters) and
  `answer: str | None` (up to 2000).
- Produces: on `Step`: `objective: int | None` (1 to 10, the place of the objective in
  `LessonBrief.objectives`), `easier: Extra | None`, `deeper: Extra | None`. On the base model
  all three are hidden from the JSON schema (as `record` is today), so today's reply shape and
  its hash do not move. Subclasses show them: one reply shape with `objective` (either planning
  switch on), one with `objective`, `easier` and `deeper` (`card_extras` on).
- Produces: a `LessonBrief` validator that clears an `objective` beyond the end of the list.
- Produces: `LessonBrief.for_agent()` leaves the three fields out when both planning switches
  are off. When the agent was not shown them, the server carries them over from the old brief
  on apply, matching steps by name, and only if the objectives are word for word unchanged.
- The field descriptions are the instruction. Deeper, not bigger: why the method works, a
  comparison, the student's own example, a case where it fails; the same numbers or smaller,
  nothing from a later step. Easier: one part of the baseline question, on the way to it.

- [ ] **Step 1: Tests.**
  - `test_a_brief_written_before_this_reads_as_it_did` (Review Focus 1).
  - `test_the_reply_shape_with_every_switch_off_is_todays` (the existing schema test stays
    green and the version is still `teacher-v26-710d809c`).
  - `test_a_step_cannot_name_an_objective_that_is_not_there`.
  - `test_what_the_agent_was_not_shown_is_kept_when_it_rewrites_the_brief`.
  - `test_when_the_objectives_change_a_carried_number_is_dropped` (Review Focus 2).
- [ ] **Step 2: See them fail.** **Step 3: Implement.** **Step 4: File, then suite, green.**
- [ ] **Step 5: Ledger line.**

### Task 8: The card shows it

**Files:**
- Modify: `backend/app/agent/cards.py`, `frontend/lib/api.ts`,
  `frontend/components/cards/lesson.tsx`
- Test: `backend/tests/test_brief_extras.py`

**Interfaces:**
- Consumes: Task 7's fields.
- Produces: each step on the card gains `objective`, `easier` and `deeper` (`null` when there
  is none). The card gains `met_when`: one entry per objective, `{"objective": <its words>,
  "lines": [the finish lines of the steps that serve it], "steps": [their names]}`. An
  objective no step serves has empty lists; the card says "No step serves this yet" and it does
  not block approval (`missing()` is unchanged).

- [ ] **Step 1: Tests:** `test_the_card_says_what_counts_as_meeting_each_objective`,
  `test_an_objective_no_step_serves_is_shown_and_does_not_block_approval`,
  `test_a_card_with_no_objectives_named_on_its_steps_is_as_it_was`.
- [ ] **Step 2: See them fail.** **Step 3: Implement the payload.** **Step 4: Suite green.**
- [ ] **Step 5: The card view:** under each objective, "Met when" and its lines; in a step's
  row, the objective it serves, and the easier step and the deeper question folded under the
  baseline. No new colours, no accent bars. A card with none of this looks as it does today.
- [ ] **Step 6: Lint, build, look on the copy.** **Step 7: Ledger line.**

### Task 9: The agent drafts the extras, and the runs

**Files:**
- Modify: `backend/bench/teacher_cases.py`, `frontend/components/teaching-settings.tsx`

**Interfaces:**
- Consumes: Task 4's variants, Task 6's switches on a case, Task 7's reply shapes.
- Produces: new keys in `RULES`: `serves` (every step names an objective that exists),
  `deeper-not-bigger` (the deeper question has no number larger than the baseline's and asks
  why, to compare, for an example or for a case that fails), `easier-is-a-part` (the easier
  step can be answered from the baseline's own numbers).

- [ ] **Step 1: Cases** for `card_extras` on (maths, English, science; a teacher who gives
  their own deeper question; a redraft that must keep the extras). Checks are plain code over
  the brief.
- [ ] **Step 2: Suite.** **Step 3: Balance, then a targeted run.** A failure is read first.
- [ ] **Step 4: Balance, then the full set** for each position a live teacher can reach that
  has not had one: extras alone, and ask-first with extras (about $1.50 each when clean).
- [ ] **Step 5: The row "Write an easier step and a deeper question for each objective"
  appears.** "They sit on the lesson card beside the baseline for you to read and change."
- [ ] **Step 6: Ledger line**, then the independent review of the whole change.

---

## After this plan

- Plan 2: the tutor (one general block, the setting from memory, the deeper question from the
  card, the easier step, the scripted run of at least 12 conversations) and the record with the
  teacher's views (tags, the words asked, a line per objective).
- The runbook for live: stage 1 first (what is built and waiting), then stages 2 to 4, then 5
  and 6. Each is a dump, tagged images, the API rebuild (which migrates), the website rebuild.
- Cut order if time runs short: the class view by objective, the Research tags, the review's
  mention, the easier step.
