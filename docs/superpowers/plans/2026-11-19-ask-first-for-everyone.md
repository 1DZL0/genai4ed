# Ask-first for everyone, no Activity box, no planning switches

Date: 19 Nov 2026. For Athens (about 23 to 27 Nov); last live change assumed Saturday 21 Nov.

## Spec: Diesel's words, 19 Nov 2026

This plan has no separate spec. Diesel's messages are the authority:

- "'Ask me questions before drafting' that doesn't need to be an option, the agent will do it
  automatically, that's the idea of the platform, along with 'Write an easier step and a deeper
  question for each objective'."
- "'Show the Activity and Tutor choices by the typing box': we are getting rid of this activity
  now, so we don't want it as an option in the backend or front, as we don't want to box a
  teacher's words into activity boxes."
- The easier step and the deeper question: "not exactly an easier step and a hard step". Later,
  the tutor will decide from each student's history to push a little (framing, fewer examples,
  style), "not impossible". Asked what happens to the two on the card now, Diesel chose: **take
  them off** (the card keeps the objectives and "Met when").
- "Ask a deeper question when a student gets a step right first time": the wrong behaviour.
  Diesel chose: **hide it for now**. A setting that lets the tutor adapt comes with the tutor
  work, later.
- The Tutor line under the typing box stays as it is: "the tutor settings we will keep a little
  simpler, but we will do that later. Do everything else first."

So, for every teacher:

1. The planning agent always asks first: it drafts a new lesson only once it has an objective,
   the students' age and the length (today's ask-first wording, `TALK_ASK_FIRST`, and the
   server's one send-back, `_lacks` / `_not_drafted_yet`, `NOT_ALL_THREE`, `NOT_AGREED`).
2. Steps name the objective they serve; the card shows "Met when". No easier step and no deeper
   question anywhere (reply shape, stored brief, card, frontend).
3. No Activity box: no headings to press above the typing box, no headings box in the chat, no
   `picks` sent or stored, no "pressed" sentences in the block the server writes. The lesson
   still has a heading and a kind, which the agent guesses from the teacher's words and says in
   one line, as today (`teacher_prompt.ACTIVITY`, the guess record).
4. The Tutor line under the typing box is always shown.
5. No planning switches: the `teaching_settings` table, model, module, route, migration and the
   Settings page's "Planning a lesson" panel go. The "Questions for each student" panel goes
   from the Settings page; the harder-question code stays, off by default and with no way to
   switch it on, until the tutor work replaces it.

## Global constraints (bind every task)

- Read CONSTRAINTS.md before writing code. No new suppression comments, no TODO/FIXME, no
  secrets. Tests of removed behaviour are removed with it; a test of behaviour that stays is
  never weakened. Say in the report which tests were removed and why.
- Backend changes test first where behaviour is new or changed. The whole suite
  (`uv run pytest -q` from backend/) is green and `scripts/check task` (from the repo root)
  clean before a task is done. Project coverage holds above 90.8%.
- Test copy only. The test database is created by the suite itself. Never run a backend command
  on default settings against a database (that is the live one). No paid model call, no bench
  run, no server start in an implementer task.
- Nothing is committed. A task ends with a suite run and a report, not a commit.
- Old data keeps loading: live messages carry `picks` and `activity` data, and live lessons
  carry `record.picked` / `picked_when`. Readers must tolerate them (do not delete
  `ActivityRecord` fields, `activities.PICKS`/`HEADINGS`, or `activities.picked_line`, which the
  research export uses to strip the old line from old messages).
- Words on screen: plain, no long dashes, ages not year groups. In code, "ladder" and "rung"
  already mean the order of help.
- Prompt rules: every rule traces to a failure seen in a run; examples and positive
  instructions over prohibitions.
- Match the surrounding code: comment density, naming (sentence-style test names), idiom.

## Task 1: one wording for every teacher, no card extras, no switches (backend)

Files: backend/app/agent/thread.py, brief.py, cards.py, teaching_settings.py (delete),
routers/teaching.py (delete), main.py (router registration), models.py (`TeachingSettings`),
alembic/versions/a3b4c5d6e7f8_teaching_settings.py (delete; the copy database has already been
taken back to f2a3b4c5d6e7 by the controller), tests.

- The wording every turn is written from is today's ask-first one with steps naming their
  objective: `teacher_prompt.system(ask_first=True)`, reply shape `TeacherTurnServing`, and the
  ask-first block sentences. Delete `Variant`, `_wording`, `_WORDINGS`, `variant`, `ASK_FIRST`
  and the reading of teaching settings in the turn. One `PROMPT_VERSION`, computed by `_version`
  over the system text, the reply schema and the block's fixed sentences, with a new label
  `teacher-v27-` (the name moves whenever the wording does, as now). Pin the computed name in a
  test as `teacher-v26-710d809c` was pinned.
- For this task keep the boxes-hidden block as it is (`STANDS_ASK_IN_WORDS` is not used under
  ask-first; `STANDS_NO_BOXES` is said last; a heading pressed does not stand). Task 2 rewrites
  the box parts.
- `teacher_prompt.system()` keeps only the ask-first talk: delete the old "How to talk" and the
  `ask_first` parameter if nothing else needs it (the bench may: Task 4 deals with the bench, so
  leave `teacher_prompt` able to give what the bench imports until then, or update the import).
- Delete `TeacherTurnWithExtras`, `BriefWithExtras`, `StepWithExtras` and the `easier` /
  `deeper` fields and their descriptions; `_keep_unshown` goes if nothing unseen remains (the
  agent sees `objective` under `TeacherTurnServing`). `cards.py` stops sending `easier` /
  `deeper`; `met_when` stays. A stored brief with old `easier`/`deeper` keys still loads (the
  models ignore unknown keys: keep it so, and keep a test that proves it).
- Delete the teaching settings: module, model, route, router registration, migration. Remove
  the `teaching_settings` import and every `of(db, ...)` call.
- Tests: the suite's default teacher now has the ask-first agent. Rewrite tests that relied on
  the old default (drafting from a topic alone) so their scripted drafts carry an objective,
  the age and the length where the test is not about asking first. Delete
  tests/test_teaching_settings.py and the switch parts of test_teacher_variants.py,
  test_ask_first.py, test_brief_extras.py (keep what still holds: objectives, "Met when",
  objective numbers, the send-back). A probe before this plan, flipping the default only, failed
  69 tests: test_brief_extras 16, test_activity_box 15, test_where_the_lesson_stands 11,
  test_teacher_variants 8, test_ask_first 7, test_thread 4, test_teacher_set 3,
  test_lesson_design_export 3, test_what_was_done_with_the_guess 1, test_prompt_caching 1.
  The activity-box failures may be left to Task 2 only if Task 2 deletes those tests; every
  other file must be green at the end of Task 1.

## Task 2: no Activity box (backend)

Files: backend/app/agent/thread.py, activities.py, scripted.py, routers/thread.py,
research.py (read only unless needed), tests.

- Delete pressing: `MessageIn.picks` and its validator (a stale client that still sends
  `picks` is not refused: check what the model does with an unknown field and keep it from
  failing), `respond(picks=...)`, the picked line added to the stored text, `data["picks"]` on
  new messages, `Pressed`, `pressed_so_far`, `_labels`, `_record_picks`, the
  `pressed=` path of `_apply_brief`, `_breaks` and `ONLY_A_TOPIC` if nothing else uses them,
  `_activity_box` / `_said_of` / `_activity` and `data["activity"]` on new messages,
  `MessageOut.activity`, `ThreadOut.activities` and `ThreadOut.picked`, `FocusOut` fields that
  only serve the box (`headings`, `picked`; keep what the lesson card needs), and
  `activities.pressed` / `for_screen` if nothing else uses them.
- The block: delete the sentences about pressing (`STANDS_BUILD`, `STANDS_REDRAFT`,
  `STANDS_ASK`, `_ASK_THE_KIND`-based ones, `STANDS_THEN_BUILD`, "Nothing is pressed in the
  activity box", "They pressed ..."). `_stands` keeps: the follow-up button, the lesson in
  focus and its heading ("your guess", or "which they pressed" for an old lesson whose record
  says so), `STANDS_THREE`, `STANDS_THEN_GUESS`, `STANDS_DRAFTED`.
  Replace `STANDS_NO_BOXES` (it said the screen has no tutor settings, which is no longer true)
  with one sentence that keeps what run v26-switched found (the agent said "Pick a heading
  below" to a teacher with no headings): the screen has no activity box and no headings to
  press, so the kind of activity is said in words. Keep the tutor settings out of it.
- The scripted test model (scripted.py) drafts from words alone where it used to need a press.
- Old data: an old message with `picks` or `activity` data still loads in the thread and the
  research export; an old lesson whose record says a heading was pressed still says "which they
  pressed" (or whatever wording Task 2 rules; record it).
- Tests: delete tests of pressing (test_activity_box.py, the pressing parts of
  test_where_the_lesson_stands.py, test_activity_in_the_lesson.py, test_thread.py,
  test_lesson_design_export.py, test_teacher_set.py); keep tests of the lesson's heading, kind,
  guess record, shape and the tutor's activity lines. Add a test that a stale client sending
  `picks` gets a normal reply and that the thread response carries no `activities`.

## Task 3: the frontend

Files: frontend/app/teacher/page.tsx, components/activity-box.tsx (delete),
components/teaching-settings.tsx, app/teacher/settings/page.tsx, components/app-header.tsx,
app/page.tsx, components/cards/lesson.tsx, components/quick-choices.tsx (one comment),
lib/api.ts.

- Lessons page: no Activity line, no in-chat headings box, no picks sent, no picked line in the
  temporary bubble. The Tutor line is always shown (no `useBoxesShown`). The blank screen always
  says the ask-first words: "Say what your students should be able to do by the end, their age
  and how long the lesson is. The agent asks for anything missing before it drafts. It keeps
  your words and fills in only what you leave out."
- Settings page: the "Planning a lesson" panel and the "Questions for each student" panel go;
  the memory panel and anything else there stays. `teaching-settings.tsx` goes if nothing is
  left in it (the shared panel helpers may move to where the memory panel needs them).
  `forgetBoxes` and its calls at sign out go.
- Lesson card: no easier step or deeper question (closed-step "easier and deeper" note, the
  open step's two blocks, every-detail answers). Objectives, "Met when", "Counts towards" stay.
  The closed step line's phone-width wrap from the last plan stays unless it only served the
  extras: say which in the report.
- lib/api.ts: remove types and calls that only served the removed parts (`TeachingSettings`,
  `teachingApi`, `ChatActivity`, `Message.activity`, `Activity`, `ThreadOut.activities`,
  `ThreadOut.picked`, `say(..., picks)`, `FocusOut.headings`/`picked`, `easier`/`deeper`).
- `scripts/check fast` clean (tsc, eslint) and `npm run build` succeeds (build on default
  settings only).

## Task 4: the bench, then one paid run (controller runs it)

Files: backend/bench/teacher_cases.py, teacher_set.py, teacher_run.py, tests/test_teacher_set.py.

- The bench runs the one wording. Remove the switch machinery (`--switches`, `SWITCHED` set,
  wording selection) and cases that press headings; keep the fifty's cases that are about the
  teacher's words, with ask-first expectations (`ASKING_FIRST` stand-ins where a case drafted
  from a topic alone), and the card rules that still apply (`serves`; drop `extras`,
  `easier-is-a-part`, `deeper-not-bigger`).
- The implementer makes no paid call. The controller checks the balance (stop below $15) and
  runs the set once on the final wording.

## After the tasks

Whole suite and `scripts/check task`; the test copy rebuilt and looked at in a browser (no
message sent): the blank screen, no Activity line, the Tutor line shown, the Settings page with
the memory panel only, a lesson card without the extras at 1280 and 400 wide. One independent
review of the whole change, one fix pass, one scoped re-check. Then the report to Diesel. Live
steps (commit, migrate, rebuild) only on Diesel's word, one at a time.
