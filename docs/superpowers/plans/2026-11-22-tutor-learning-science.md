# Tutor Learning-Science Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the seven tutor changes and the class agent's depth hint as guidance, and measure the new prompts against today's on situations built for each change.

**Architecture:** A harness (`bench/tutor_ab.py`) seeds fixed situations in a scratch database, drives scripted student messages through the real `StudentAgent.respond`, and has a different model judge each transcript blind. It is committed before any prompt change, so today's prompt runs from a git worktree at that commit and the new one from the working tree. The prompt changes are text in `scaffold.py` and `teacher_prompt.py` plus one optional assessment field.

**Tech Stack:** Python 3.12, FastAPI app code, SQLAlchemy async, Postgres (container genai4ed-db), OpenRouter, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-tutor-learning-science-design.md`

## Global Constraints

- Guidance only: no server gate, threshold or regeneration keyed on any new field or sentence.
- The harness writes only to the database `genai4ed_ab`; it refuses any other name. Never the live `genai4ed`, the copy `genai4ed_memory` or the tests' `genai4ed_test`.
- No key or `.env` value is printed by any script.
- Judge model `anthropic/claude-sonnet-5.5`; the tutor model is whatever the settings say (today Opus 5.5).
- Three runs per situation per version. Total spend about $8 to $12.
- Depth of knowledge, not Bloom. Plain words, no long dashes, in prompt text and reports.
- No deploy. Commits on `backup/2026-11-01`, pushed only on Diesel's word.

## Review Focus

- A situation whose scripted messages run past the lesson's last step: the harness stops at the end, it does not error.
- The tutor call failing (`AgentUnavailable`) mid-situation: the run is recorded as failed with the reason, the rest go on.
- The judge returning something unusable: retried once, then marked "no verdict", never counted as a pass.
- The judge seeing which prompt wrote a transcript: the version string and the field names that only the new version has are not in what it reads.
- A student-visible reply carrying the new diagnosis words ("knowledge error"): T1 is recorded, not said; situation 1's judge criterion includes that the student is not labelled.

---

### Task 1: The harness, the situations and the depth case, before any prompt change

**Files:**
- Create: `backend/bench/tutor_ab.py` (seeding, running, judging, report, CLI)
- Create: `backend/bench/tutor_ab_cases.py` (the nine situations)
- Modify: `backend/bench/teacher_cases.py` (case `depth-across-steps`)
- Test: `backend/tests/test_tutor_ab.py`

**Interfaces:**
- Produces: `Situation` (frozen dataclass: `id: str`, `targets: tuple[str, ...]`, `subject: str`, `age: int`, `steps: tuple[dict, ...]`, `rules: dict`, `adapt: bool`, `memory_learns: tuple[str, ...]`, `memory_knows: tuple[str, ...]`, `student: tuple[str, ...]`, `criteria: tuple[str, ...]`, `judged_reply: int = -1`); `SITUATIONS: tuple[Situation, ...]`.
- Produces: `async def seed(db, s: Situation) -> Seeded` (teacher, student, contract, session); `async def run_one(db, s: Situation, agent: StudentAgent) -> Run` (`transcript: list[dict]`, `fields: list[dict]` per tutor turn from the turn records, `error: str | None`, `prompt_version: str`); `def judge_input(s: Situation, run: Run) -> str`; `async def judge(client, s, run) -> list[Verdict]` (`criterion`, `passed: bool | None`, `reason`); `def report(old: list[dict], new: list[dict]) -> str`.
- CLI: `uv run python -m bench.tutor_ab --label old|new --repeat 3 [--only ids]` saves `bench/out/tutor-ab-<label>.json`; `--compare old new` prints the table.

- [ ] **Step 1: Write the failing tests** in `tests/test_tutor_ab.py`, with `ScriptedClient` (no network) and the tests' own database fixtures:
  - `test_a_situation_is_seeded_with_its_rules_memory_and_adapting`: seeding situation 5 gives a session whose brief has `rules.adapt_to_student is True` and a learner note whose lines include "needs help twice".
  - `test_a_run_drives_every_scripted_message_and_keeps_each_reply`: running situation 2 with a scripted tutor gives a transcript of `2 * len(s.student)` lines, alternating student and tutor (plus the tutor's opening if the agent gives one), and `fields` with one entry per tutor turn.
  - `test_the_judge_reads_no_version`: `judge_input` for any situation contains neither "student-v" nor "error_kind" nor "pitch".
  - `test_an_unusable_verdict_is_no_verdict`: a judge reply without `passed` gives `passed is None`, and `report` counts it as not passed and shows it as "no verdict".
  - `test_the_harness_refuses_any_other_database`: the database guard raises for `genai4ed`, `genai4ed_memory` and `genai4ed_test`.
  - `test_there_is_a_situation_for_every_change`: the union of `targets` over `SITUATIONS` is exactly `{"T1".."T7"}` and there are nine situations, ids `1-misconception`, `2-reasoning-slip`, `3-clumsy-english`, `4-after-hints`, `5-struggling`, `6-switched-off`, `7-second-language`, `8-overload`, `9-raise-thinking`, with the spec's pass criteria as their `criteria`.
- [ ] **Step 2: Run them to see them fail**: `uv run pytest tests/test_tutor_ab.py -q`, expected: import errors.
- [ ] **Step 3: Write `tutor_ab_cases.py` and `tutor_ab.py`.** Memory through `learner.write(...)` with review lines; adapting through `rules.adapt_to_student`; the scratch database is created if missing and its tables are rebuilt as the tests' `engine` fixture does; the judge is the app's `OpenRouterClient` with the judge model and a two-field schema (`passed`, `reason`), one call per criterion, retried once on an unusable reply. Situation 1's criteria include "does not label the student or name an error type to them".
- [ ] **Step 4: Add teacher case `depth-across-steps`**: a teacher message that gives goal, age and length for a history lesson; checks `drafts()` and that at least one step's text asks them to explain, compare, justify or judge (`r"\bwhy\b|explain|compare|justify|which (?:mattered|was) (?:more|most)|how far|convince|evaluate"` over the steps' JSON).
- [ ] **Step 5: Run**: `uv run pytest tests/test_tutor_ab.py tests/test_teacher_set.py -q`, expected all pass; `uv run ruff check bench tests && uv run ruff format --check bench tests`.
- [ ] **Step 6: Commit** the four files: "Tutor A/B harness: nine situations, a blind judge, old against new". This commit is the baseline.

### Task 2: Today's prompt, measured

**Files:** none changed. A worktree at Task 1's commit: `git worktree add ../genai4ed-ab-old <task-1-sha>`.

- [ ] **Step 1:** In the worktree's `backend/`, `uv sync`, then run with the repo's settings exported from `../../genai4ed/.env` without printing them: `uv run python -m bench.tutor_ab --label old --repeat 3`, writing to the main tree's `backend/bench/out/`. Expected: 27 runs, the prompt version printed is today's `student-v21-...`.
- [ ] **Step 2:** In the same worktree: `uv run python -m bench.teacher_set --only depth-across-steps --repeat 3 --label depth-old`. Record the pass count.

### Task 3: The tutor changes T1 to T7

**Files:**
- Modify: `backend/app/agent/scaffold.py` (`TEACH`, and in `PITCH` the Reasoning and Judgement lines point to depth of knowledge)
- Modify: `backend/app/agent/tutor_reply.py` (`AssessmentOut.error_kind`)
- Modify: `backend/app/enums.py` (`ErrorKind`: `knowledge`, `reasoning`, `expression`)
- Test: `backend/tests/test_tutor_prompt.py`, `backend/tests/test_learning_science.py` (new)

**Interfaces:**
- Produces: `ErrorKind(StrEnum)`; `AssessmentOut.error_kind: ErrorKind | None = None` with a description that it is recorded, never said to the student.

- [ ] **Step 1: Write the failing tests** in `tests/test_learning_science.py`:
  - `test_how_to_teach_carries_each_change`: `TEACH` contains a sentence for each of T1 to T6 (assert on a short key phrase each: the three causes; "comparable question" and "without help"; "refut"; "words" separately from "thinking"; "support" before "an easier question"; "check-in"), and the fixed parts name the four depths of knowledge.
  - `test_no_new_rule_is_enforced`: `supervisor` and `student_mode` do not reference `error_kind`.
  - `test_error_kind_is_optional_and_named`: `AssessmentOut(judgment="not_met").error_kind is None`; `AssessmentOut(judgment="not_met", error_kind="expression").error_kind is ErrorKind.EXPRESSION`; an unknown value fails validation.
  - `test_the_student_prompt_version_changed`: `student_mode.prompt_version()` is not today's version.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Write the sentences** in the prompts' plain style, short, one idea each, following the spec's T1 to T7. Update tests that pin today's wording or version on purpose.
- [ ] **Step 4: Run** `uv run pytest -q` (the whole suite), ruff check and format. Expected: all pass.
- [ ] **Step 5: Commit**: "Tutor: why an answer is wrong, supported is not independent, support not less demand, depth of knowledge".

### Task 4: The class agent's depth hint (C1)

**Files:** Modify `backend/app/agent/teacher_prompt.py` (one sentence where drafting is described); tests that pin the version.

- [ ] **Step 1:** Run `uv run python -m bench.teacher_set --only depth-across-steps --repeat 3 --label depth-new-red` on today's teacher prompt (the working tree before this task). Record it (it may already pass: the case measures, it does not have to fail).
- [ ] **Step 2:** Add the sentence; update `test_one_wording.TODAY`.
- [ ] **Step 3:** Run the case again (`--label depth-new`, three runs), then the full teacher set (`--label v27-depth --against v27-human-2`). Expected: 60 of 60 or the same as before plus the new case.
- [ ] **Step 4:** Run the whole suite; commit: "Class agent: vary the kind of thinking across the steps".

### Task 5: The new prompt, measured, and the report

- [ ] **Step 1:** In the main tree: `uv run python -m bench.tutor_ab --label new --repeat 3`.
- [ ] **Step 2:** `uv run python -m bench.tutor_ab --compare old new`: one row per situation and criterion, old passes out of 3 against new, and the `error_kind` counts for the new version.
- [ ] **Step 3:** Write the table and the judge's reasons for every change in pass rate into `backend/bench/RESULTS.md` under "22 Nov 2026: learning-science guidance", in plain words, and the depth case's old and new counts.
- [ ] **Step 4:** Remove the worktree (`git worktree remove ../genai4ed-ab-old`). Commit RESULTS.md: "Results: the learning-science prompts against today's".
