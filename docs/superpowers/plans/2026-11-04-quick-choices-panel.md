# Quick Choices Panel and Depth Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the tutor's rule switches under the teacher's typing box from the first screen, make depth (1 to 4) one of them, have the agent read the rules back, and report each student's deepest rung in the end summary.

**Architecture:** The lesson gains a depth in its compiled rules; steps take it unless the teacher named one, and the tutor's scaffold, the card and the summary all read the effective depth through one method. A shared frontend module holds the choices, the sentences they compose, and a read-back row that renders the same rule values the card's pills use, sourced from the focused lesson. The teacher agent's prompt learns to route depth into the rules and to point at the switches.

**Tech Stack:** FastAPI + SQLAlchemy async + Pydantic (backend, `uv run pytest` against Postgres); Next 16 + React 19 + Tailwind v4 (frontend, `tsc --noEmit` + `eslint`, no test runner).

**Spec:** `docs/superpowers/specs/2026-11-04-quick-choices-panel-design.md`

## Global Constraints

- No em or en dashes anywhere in UI text, prompts, comments or commit messages; use commas, colons, full stops.
- Pseudonyms only in examples and tests (`9W-02`, `teacher-1`); no real names.
- Frontend colours only from the tokens in `frontend/app/globals.css` (paper, sheet, sunken, rule, ink, pencil, progress, progress-wash). Fonts and spacing unchanged.
- The student prompt's `DOK_WORDS` and the review prompt's depth sentence are not edited. Changing `scaffold.TEACH` is accepted and bumps the tutor prompt hash on its own; `review-v3` stays.
- Backend: `cd backend && uv run pytest -q` must stay green (293 today). Frontend: `cd frontend && npx tsc --noEmit && npm run lint` clean.
- Commits in this plan are local only, never pushed, and only with the owner's go-ahead. Without it, run every step except the commit steps and leave the tree uncommitted.
- Scratch output (screenshots) goes in `.superdesign/tmp/`, never in the repo.

## Review Focus

1. A teacher message that merely mentions a depth ("what does depth 3 mean?") must not change the lesson's depth; only "teach to depth N" or one of the four rung phrases does. Test in Task 1 (`depth_from_words`), applied in Task 4.
2. A step the teacher set to depth 2 inside a lesson at depth 3 keeps 2; the switch never overrides a named step. Test in Task 1.
3. Every sentence the panel composes must survive the literal parser, or the switch silently depends on the model: "A worked step after 2 wrong tries.", "A worked step straight away.", "The answer itself: never.", "The answer if they ask.". Tests in Task 1 use the exact strings Task 5 emits.
4. The read-back row must never state a value the card does not: with a lesson card on screen it reads that card; otherwise the focused lesson; defaults only when no lesson exists. One helper `ruleValuesFrom` feeds both the row and the comparison with the pills. Manual check in Task 5.
5. With browser storage unavailable (private window) the panel still opens on first visit and the page renders. Manual check in Task 5.

---

### Task 1: Depth in the rules, the teacher's words, and the card (backend)

**Files:**
- Modify: `backend/app/agent/policy.py` (PolicyRules, labels, describe, from_teachers_words, regexes near line 223)
- Modify: `backend/app/agent/brief.py:67-69` (Step.depth property)
- Modify: `backend/app/agent/scaffold.py:208-210` (step_block target line)
- Modify: `backend/app/agent/cards.py:174` and `:185-189` (step depth; card rule fields)
- Modify: `backend/app/agent/context.py:335`
- Modify: `backend/app/agent/student_mode.py:488`, `:696-701` (`_note_help_given`), `:710-727` (`_measured`) and their call sites
- Test: `backend/tests/test_agent_core.py`, `backend/tests/test_tutor_prompt.py`

**Interfaces:**
- Produces: `DEPTH_PLAIN: dict[int, str]` in `policy.py` = `{1: "recall it", 2: "apply it or explain it", 3: "justify it", 4: "take it further"}`.
- Produces: `PolicyRules.depth: int` (1 to 4, default 2).
- Produces: `depth_from_words(text: str) -> int | None` in `policy.py`.
- Produces: `Step.depth_in(rules: PolicyRules) -> int` replacing the `depth` property.
- Produces: lesson card JSON gains `"depth": int` and `"answer_after": int | None` beside `worked_step_after`.

- [ ] **Step 1: Write the failing tests in `test_agent_core.py`** (after `test_the_teachers_plainest_rule_sentences_are_taken_literally`)

```python
def test_depth_is_taken_literally_from_the_teachers_words():
    from app.agent.policy import PolicyRules, depth_from_words, from_teachers_words

    assert from_teachers_words(PolicyRules(), "Teach to depth 3: students should justify it.").depth == 3
    assert from_teachers_words(PolicyRules(), "Students should take it further.").depth == 4
    assert from_teachers_words(PolicyRules(), "Hints are fine.").depth == 2
    assert depth_from_words("What does depth 3 mean?") is None
    assert depth_from_words("teach to depth 1 today") == 1


def test_the_switch_sentences_are_taken_literally():
    from app.agent.policy import PolicyRules, from_teachers_words

    fixed = from_teachers_words(PolicyRules(), "A worked step after 2 wrong tries. The answer itself: never.")
    assert (fixed.partial_after_attempts, fixed.full_answer_after_attempts) == (2, None)
    assert from_teachers_words(PolicyRules(), "A worked step straight away.").partial_after_attempts == 0
    assert from_teachers_words(PolicyRules(), "The answer if they ask.").full_answer_after_attempts == 0


def test_the_depth_is_a_pill_and_a_sentence():
    from app.agent.policy import PolicyRules

    assert "Teach to depth 2, apply it or explain it" in PolicyRules().labels()["pills"]
    assert "The tutor teaches to depth 3: justify it." in PolicyRules(depth=3).describe()
```

Also update `test_the_rules_become_short_labels_for_the_card` (line 176): the default pills list becomes `["Hints any time", "Worked step after 1 wrong try", "Never gives the answer", "Teach to depth 2, apply it or explain it", "Never writes their work"]`.

- [ ] **Step 2: Write the failing tests in `test_tutor_prompt.py`**, replacing `test_a_step_knows_its_depth_in_any_subject` (line 255):

```python
def test_a_step_takes_the_lessons_depth_unless_the_teacher_set_its_own():
    rules = PolicyRules(depth=3)
    assert Step(name="Date", kind=StepKind.CHECK, goal="When was it?").depth_in(rules) == 3
    assert Step(name="Why", kind=StepKind.QUESTION, goal="Why?", target_dok=2).depth_in(rules) == 2
    assert Step(name="Date", kind=StepKind.CHECK, goal="When?").depth_in(PolicyRules()) == 2
    with pytest.raises(ValueError):
        Step(name="x", kind=StepKind.CHECK, goal="y", target_dok=5)


def test_the_step_block_says_whose_depth_it_is():
    deeper = BRIEF.model_copy(update={"rules": PolicyRules(depth=3)})
    block = scaffold.step_block(deeper, 1, task=None)
    assert "Target depth: 3 (justify, compare approaches, or use evidence), the lesson's depth." in block
    named = BRIEF.model_copy(deep=True)
    named.steps[1].target_dok = 2
    assert "Target depth: 2 (apply a method, or explain a concept)." in scaffold.step_block(named, 1, task=None)
```

And in `test_a_preview_shows_the_teacher_how_step_1_opens_without_touching_a_student` (line 249), after the steps assertion add `assert (card["depth"], card["answer_after"]) == (2, None)`.

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_agent_core.py tests/test_tutor_prompt.py -q -k "depth or switch_sentences or labels_for_the_card or step_block_says"`
Expected: FAIL (no `depth` field, no `depth_in`, no `depth_from_words`).

- [ ] **Step 4: Implement in `policy.py`**
  - `DEPTH_PLAIN` next to `SIGNAL_WORDS`.
  - `PolicyRules.depth: int = Field(default=2, ge=1, le=4, description="How deep the tutor pushes a right answer, 1 to 4 (Webb): the lesson's depth for every step the teacher did not set one for.")`.
  - `labels()`: insert the pill `f"Teach to depth {self.depth}, {DEPTH_PLAIN[self.depth]}"` after the answer pill, before the ladder pill.
  - `describe()`: add `f"The tutor teaches to depth {self.depth}: {DEPTH_PLAIN[self.depth]}."` after the answer line.
  - Regexes: `_TRIES = r"(?:wrong )?(?:tries|attempts|goes|tr(?:y|ies)|answers|times)"`; add `_WORKED_NOW` (worked step/example/solution … `straight away|from the start|at once` → 0); `_ANSWER_ITSELF_NEVER = r"\banswer(?: itself)?\b[^.]{0,20}?\bnever\b"` → None; `_ANSWER_IF_ASKED = r"\banswer\b[^.]{0,40}?\b(?:if they ask|when asked|when they ask)\b"` → 0; `_TEACH_TO_DEPTH = r"\bteach(?:ing)? to depth ([1-4])\b"`; `_DEPTH_PHRASES = {phrase: n for n, phrase in DEPTH_PLAIN.items()}` matched case-insensitively as whole phrases.
  - `def depth_from_words(text: str) -> int | None`: the number from `_TEACH_TO_DEPTH` wins; else the first rung phrase found; else None.
  - `from_teachers_words`: apply the new patterns; set `depth` when `depth_from_words` returns a value.

- [ ] **Step 5: Implement `Step.depth_in(self, rules: PolicyRules) -> int` in `brief.py`** returning `self.target_dok or rules.depth`; delete the `depth` property. Update every caller: `scaffold.step_block` (`target = step.depth_in(brief.rules)`; suffix `", the lesson's depth"` when `step.target_dok` is None, nothing when set); `cards.py:174` (`s.depth_in(brief.rules)`) and add `"depth": brief.rules.depth, "answer_after": brief.rules.full_answer_after_attempts` beside `worked_step_after`; `context.py:335` (`g.step.depth_in(g.brief.rules)`); `student_mode.py:488`; `_note_help_given(on_step, out, step, target: int | None)` and `_measured(..., target: int | None)` take the effective depth from their callers (`step.depth_in(brief.rules) if step else None`) instead of reading `step.depth`.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass (293 plus the new ones).

- [ ] **Step 7: Commit (only with the owner's go-ahead)**

```bash
git add backend/app/agent/policy.py backend/app/agent/brief.py backend/app/agent/scaffold.py backend/app/agent/cards.py backend/app/agent/context.py backend/app/agent/student_mode.py backend/tests/test_agent_core.py backend/tests/test_tutor_prompt.py
git commit -m "Depth is a rule of the lesson: steps take it unless the teacher named one"
```

---

### Task 2: The tutor asks twice at depth 3 and 4

**Files:**
- Modify: `backend/app/agent/scaffold.py:52-71` (TEACH), `:345-366` (Noticed), `:403-408` (noticed_block depth line)
- Modify: `backend/app/agent/context.py:355` and `backend/app/agent/student_mode.py:747` (Noticed construction)
- Test: `backend/tests/test_tutor_prompt.py`

**Interfaces:**
- Consumes: `Step.depth_in(rules)` from Task 1.
- Produces: `scaffold.Noticed.target_depth: int = DOK_DEFAULT`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_tutor_may_ask_twice_for_depth_only_at_three_or_four():
    once = scaffold.noticed_block(scaffold.Noticed(depth_asks=1, target_depth=2))
    assert "do not ask again" in once
    more = scaffold.noticed_block(scaffold.Noticed(depth_asks=1, target_depth=3))
    assert "you may ask once more" in more and "do not ask again" not in more
    stop = scaffold.noticed_block(scaffold.Noticed(depth_asks=2, target_depth=4))
    assert "do not ask again" in stop
    assert "twice when the target depth is 3 or 4" in scaffold.TEACH
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_tutor_prompt.py -q -k ask_twice`
Expected: FAIL (`target_depth` unknown).

- [ ] **Step 3: Implement**
  - `Noticed.target_depth: int = DOK_DEFAULT`.
  - `noticed_block`: `allowed = 2 if n.target_depth >= 3 else 1`; when `n.depth_asks >= allowed` keep today's "do not ask again; move on with what they give" line; otherwise `f"You have asked for the why on this step {times}: at this depth you may ask once more, then move on with what they give."`
  - `TEACH`: change "ask once for what is missing, then move on" to "ask for what is missing (once; twice when the target depth is 3 or 4), then move on".
  - Pass `target_depth=step.depth_in(brief.rules)` at both constructions (`context.py:355`, `student_mode.py:747`).

- [ ] **Step 4: Run the suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit (only with the owner's go-ahead)**

```bash
git add backend/app/agent/scaffold.py backend/app/agent/context.py backend/app/agent/student_mode.py backend/tests/test_tutor_prompt.py
git commit -m "At depth 3 and 4 the tutor asks for the why twice before moving on"
```

---

### Task 3: The deepest rung each student reached

**Files:**
- Modify: `backend/app/agent/classroom.py` (new `deepest_shown`; `suggest_outcomes` near line 635)
- Modify: `frontend/lib/api.ts:306-312` (`Outcome.suggested`)
- Modify: `frontend/components/cards/outcomes.tsx:184-186`
- Test: `backend/tests/test_tutor_prompt.py`

**Interfaces:**
- Produces: `async def deepest_shown(db: AsyncSession, session_id: uuid.UUID) -> dict[uuid.UUID, int]` (largest recorded `depth_shown` per student; students with none absent).
- Produces: `LessonOutcome.suggested["deepest"]: int | None`, passed through to the card as `suggested.deepest` (cards.py already returns `suggested` whole at line 312).

- [ ] **Step 1: Write the failing test** (in `test_tutor_prompt.py`, which already imports `student_says`, `turn`, `lesson`)

```python
async def test_the_summary_carries_the_deepest_rung_each_student_reached(db, lesson):
    from app.agent.classroom import deepest_shown

    shallow = turn("Yes.", student_attempted=True, assessment={"judgment": "met", "evidence_quote": "5", "depth_shown": 1})
    deep = turn("Good reason.", student_attempted=True, assessment={"judgment": "met", "evidence_quote": "because", "depth_shown": 3})
    await student_says(db, lesson, ScriptedClient([shallow]), "5")
    await student_says(db, lesson, ScriptedClient([deep]), "because 15/3")
    deepest = await deepest_shown(db, lesson.session.id)
    assert deepest == {lesson.alice.id: 3}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_tutor_prompt.py -q -k deepest`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `deepest_shown`** as one query over `EvidenceRecord` with `kind == ASSESSMENT` and `payload["depth_shown"]` not null, grouped by `student_id` with `max`. In `suggest_outcomes`, call it once before the loop and add `"deepest": deepest.get(o.student_id)` to `suggested` beside `"depth": o.depth_note`.

- [ ] **Step 4: Frontend**: `Outcome.suggested.deepest?: number | null;` in `api.ts`; in `outcomes.tsx` after the `depth` line render `{typeof outcome.suggested.deepest === "number" && (<p className="text-sm text-pencil">Deepest: {DEPTH_PLAIN[outcome.suggested.deepest]} ({outcome.suggested.deepest})</p>)}` importing `DEPTH_PLAIN` from `@/components/quick-choices` (Task 5 creates it; if Task 3 runs first, create that file with only `DEPTH_PLAIN` and Task 5 extends it).

- [ ] **Step 5: Run the suite and the frontend checks**

Run: `cd backend && uv run pytest -q && cd ../frontend && npx tsc --noEmit && npm run lint --silent`
Expected: all pass, clean.

- [ ] **Step 6: Commit (only with the owner's go-ahead)**

```bash
git add backend/app/agent/classroom.py backend/tests/test_tutor_prompt.py frontend/lib/api.ts frontend/components/cards/outcomes.tsx frontend/components/quick-choices.tsx
git commit -m "The end summary says the deepest rung each student reached"
```

---

### Task 4: The teacher agent routes depth and points at the switches

**Files:**
- Modify: `backend/app/agent/thread.py:86-93` (What goes on the card), `:111-115` (Depth targets), `:148-152` (Teaching approaches), `:648-651` (`_RULE_WORDS`), `:688-691` (`_apply_brief`)
- Modify: `backend/app/routers/thread.py:87-93` (`FocusOut`) and its construction at `:139`
- Test: `backend/tests/test_thread.py`

**Interfaces:**
- Consumes: `depth_from_words` and `PolicyRules.depth` from Task 1.
- Produces: `FocusOut` gains `help: dict` (from `rules.labels()`), `worked_step_after: int`, `hints_allowed: bool`, `answer_after: int | None`, `depth: int`.

- [ ] **Step 1: Write the failing tests** (in `test_thread.py`)

```python
def test_the_agent_is_told_to_read_the_rules_back_and_not_to_point_at_approach_tiles():
    from app.agent.thread import SYSTEM, _RULE_WORDS

    assert "read the rules back in one plain sentence" in SYSTEM
    assert "quick choices under the box" in SYSTEM
    assert "approach tiles" not in SYSTEM
    assert "only when the teacher named a depth for that step" in SYSTEM
    assert _RULE_WORDS.search("teach to depth 3")


async def test_the_focus_carries_the_lessons_rule_values(db, client, classroom):
    shown = await press(client, classroom, "show_lesson", lesson_id=classroom.contract.id)
    focus = shown.json()["focus"]
    assert (focus["depth"], focus["worked_step_after"], focus["answer_after"]) == (2, 1, None)
    assert "Teach to depth 2, apply it or explain it" in focus["help"]["pills"]
```

(If `press` returns the parsed thread rather than a response, read `focus` from it the way neighbouring tests read `last_card`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_thread.py -q -k "read_the_rules_back or focus_carries"`
Expected: FAIL.

- [ ] **Step 3: Edit the prompt in `thread.py`**
  - Replace the "Depth targets" paragraph (111 to 115) with: the lesson has one depth, `rules.depth`, 1 to 4 (1 recall it; 2 apply it or explain it; 3 justify it; 4 take it further); set `rules.depth` from "teach to depth N" or one of those four phrases and put that sentence in `rules_text`; set a step's `target_dok` only when the teacher named a depth for that step, otherwise leave it empty; say the depth once, in one line, when you draft.
  - In "What goes on the card" (86 to 93) add: after drafting or changing a lesson, read the rules back in one plain sentence (hints, worked step, the answer, depth, what interrupts the teacher) and say the quick choices under the box change any of them; this sentence is the one exception to repeating what is on the card; never claim to have changed a switch yourself.
  - Delete the "Teaching approaches" paragraph (148 to 152).
  - `_RULE_WORDS`: add `|depth|deeper`.
  - `_apply_brief`: after line 691 add `if (d := depth_from_words(said)) is not None: out.brief.rules = out.brief.rules.model_copy(update={"depth": d})`.

- [ ] **Step 4: Extend `FocusOut`** with the five fields and fill them at `routers/thread.py:139` from `LessonBrief.model_validate(lesson.brief or {}).rules` (`labels()`, `partial_after_attempts`, `hints_allowed`, `full_answer_after_attempts`, `depth`).

- [ ] **Step 5: Run the suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass. (The tutor prompt hash changes; no test pins it.)

- [ ] **Step 6: Commit (only with the owner's go-ahead)**

```bash
git add backend/app/agent/thread.py backend/app/routers/thread.py backend/tests/test_thread.py
git commit -m "The teacher agent reads the rules back and routes depth into them"
```

---

### Task 5: The quick choices under the box (frontend)

**Files:**
- Create: `frontend/components/quick-choices.tsx`
- Modify: `frontend/app/teacher/page.tsx:203-270` (composer fragment), `:194-195` (focus, blank)
- Modify: `frontend/components/cards/lesson.tsx:20-28` (DEPTH_WORDS), `:112` (QuickChoices on the card), `:349-362` (DepthLabel), `:630-737` (CHOICES and QuickChoices move out), `:792-795` (note text)
- Modify: `frontend/lib/api.ts:328-375` (`LessonCard`), `:516` (`Focus`)
- Test: `npx tsc --noEmit`, `npm run lint`, and a render at 1280 and 420 (below)

**Interfaces:**
- Consumes: `LessonCard.depth`, `LessonCard.answer_after` (Task 1) and the extended `Focus` (Task 4).
- Produces, all exported from `components/quick-choices.tsx`:
  - `DEPTH_PLAIN: Record<1 | 2 | 3 | 4, string>` (same four strings as the backend).
  - `type RuleValues = { hints: boolean; workedAfter: number; answerAfter: number | null; depth: number; atOnce: string[] }`.
  - `DEFAULT_RULES: RuleValues` = `{ hints: true, workedAfter: 1, answerAfter: null, depth: 2, atOnce: ["a student who's upset", "a student who asks for you"] }` with a comment naming `backend/app/agent/policy.py` as the source of truth.
  - `ruleValuesFrom(source: Pick<LessonCard, "help" | "worked_step_after" | "hints_allowed" | "answer_after" | "depth"> | Focus): RuleValues`.
  - `readBack(rules: RuleValues, hasLesson: boolean): string`.
  - `CHOICES` (groups), `composeChoices(picked: Record<string, string[]>): string`.
  - `QuickChoicesPanel({ onWords, busy, open, onToggle, focusGroup }: { onWords: (words: string) => void; busy: boolean; open: boolean; onToggle: () => void; focusGroup: string | null })`.
  - `RuleReadBack({ rules, hasLesson, onTap, onShowAll }: { rules: RuleValues; hasLesson: boolean; onTap: (group: string) => void; onShowAll: () => void })`.

- [ ] **Step 1: Create `quick-choices.tsx`** with the groups below (move `CHOICES` and the panel body out of `lesson.tsx`; the panel's markup, fieldsets and pill buttons stay as they are today, only the wrapper changes from `<details>` to a controlled block):

| Group | Options | Sentence composed (exact) |
|---|---|---|
| Type of task | as today | `Type of task: {opts}.` |
| Questions | as today | `Questions: {opts}.` |
| How deep | `1 · recall it`, `2 · apply it or explain it`, `3 · justify it`, `4 · take it further` | `Teach to depth N: students should {phrase}.` |
| Hints towards the answer | `on`, `off` | on: nothing; off: `No hints towards answers.` |
| A worked step | `straight away`, `after 1 wrong try`, `after 2 wrong tries`, `after 3 wrong tries` | `A worked step {option}.` |
| The answer itself | `never`, `after 2 wrong tries`, `if they ask` | never: `The answer itself: never.`; else `The answer {option}.` |
| At the end | as today | `At the end: {opts}.` |
| Tone | as today | `Tone: {opts}.` |
| Tell me straight away when a student | as today, multi | `Tell me straight away when a student {a, b and c}.` |

`composeChoices` prefixes `"Please use these choices for this lesson. "` and joins the group sentences with a space, as today. `readBack` produces, with no lesson: `Unless you say otherwise, I'll give {hints}, a worked step {worked}, {answer} the answer, and teach to depth {d}, {DEPTH_PLAIN[d]}. I'll tell you at once about {atOnce}. Tap any of those to change it, or show all the quick choices.`; with a lesson the same sentence opening `For this lesson I'll give …` and without the last sentence. Words: hints `hints any time` | `no hints towards the answer`; worked `straight away` | `after 1 wrong try` | `after N wrong tries`; answer `never` | `after N wrong tries` | `if they ask`; `atOnce` joined with commas and "and". `ruleValuesFrom` builds `atOnce` from `help.at_once[].words` lowercased, always including the two defaults.

`RuleReadBack` renders the pencil (`TutorFace` from `@/components/chat`) and the sentence; the four values (worked, answer, depth, atOnce) are `<button type="button">` styled `rounded-t-[4px] border-b-2 border-progress bg-progress-wash px-1 font-semibold text-ink`, each calling `onTap(group)` with the group name from the table; "show all the quick choices" is a button calling `onShowAll`.

- [ ] **Step 2: Wire the teacher page.** In the `composer` fragment, after `<Composer … />`, render `<RuleReadBack rules={rules} hasLesson={hasLesson} onTap={openAt} onShowAll={() => setChoicesOpen(!choicesOpen)} />` and `<QuickChoicesPanel onWords={onWords} busy={busy} open={choicesOpen} onToggle={…} focusGroup={focused} />`, where:
  - `hasLesson = Boolean(data?.focus)`; `rules = showing?.type === "lesson" ? ruleValuesFrom(showing) : data?.focus ? ruleValuesFrom(data.focus) : DEFAULT_RULES`.
  - `onWords(words)`: if `!hasLesson`, compose into the box: keep `lastComposed` in a ref; `setText((t) => (lastComposed.current && t.includes(lastComposed.current) ? t.replace(lastComposed.current, words) : (t.trimEnd() ? t.trimEnd() + "\n" + words : words)))`, set the ref, focus `boxRef`; if `hasLesson`, `void send(words)`.
  - `choicesOpen` initial value: the `localStorage` key `genai4ed.quickChoices.open` if readable (inside try/catch), else `true` when the SWR `"thread-lessons"` list is loaded and empty, else `false`; write the key on toggle inside try/catch.
  - `openAt(group)`: open the panel and set `focused = group`; the panel scrolls that fieldset into view and focuses its first button on the next frame.
  - The panel's action button keeps its label "Tell the agent" when `hasLesson`, and reads "Put it in the box" when not.

- [ ] **Step 3: The lesson card.** In `lesson.tsx`: delete `DEPTH_WORDS` and `CHOICES`/`QuickChoices`; `DepthLabel` reads `DEPTH_PLAIN`; render `<QuickChoicesPanel onWords={say} busy={busy} open={draft} onToggle={…} focusGroup={null} />` where the old `<details>` was, preceded (when not draft) by a visible `Button variant="quiet"` labelled "Quick choices" that toggles it; keep the `say &&` guard; change the step note at 792 to "Steps take the lesson's depth unless you set one for a step. To change one, say so in the chat."

- [ ] **Step 4: Types.** `LessonCard` gains `answer_after: number | null; depth: number;` and `Focus` becomes `{ lesson_id: string; title: string; status: string; help: LessonCard["help"]; worked_step_after: number; hints_allowed: boolean; answer_after: number | null; depth: number }`.

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint --silent`
Expected: clean.

- [ ] **Step 6: Render both states and both widths.** With the local frontend on :3001 against the live api, reuse the Playwright script pattern in the session scratchpad (`pw/render.mjs`): sign in as Teacher 1, screenshot the blank create screen at 1280 and 420 (row visible under the box, panel open), open the "Linear equations" lesson so the row reads its rules, press "3 · justify it" then "Tell the agent" and confirm the card's pills now show "Teach to depth 3, justify it". Save to `.superdesign/tmp/quick-choices-*.png`. Then in a private window confirm the page renders and the panel is open on first visit.

Expected: the row's values match the card's pills in every screenshot; no horizontal scroll at 420px.

- [ ] **Step 7: Commit (only with the owner's go-ahead)**

```bash
git add frontend/components/quick-choices.tsx frontend/app/teacher/page.tsx frontend/components/cards/lesson.tsx frontend/lib/api.ts
git commit -m "Quick choices sit under the teacher's box, with depth as a switch"
```

---

## Self-review notes

- Spec coverage: placement in both states (Task 5), agent read-back (Task 4), depth switch end to end (Tasks 1, 4, 5), ask-twice (Task 2), deepest rung (Task 3), one control not two (Task 5 step 3), approaches mention removed (Task 4), accessibility and tokens (Task 5 steps 1 and 2 name the elements and classes). The spec's "localStorage inside try/catch" and "first visit" rule are in Task 5 step 2.
- Type consistency: `depth_in(rules)` is used by Tasks 1 and 2; `DEPTH_PLAIN` strings are identical in `policy.py` and `quick-choices.tsx`; `FocusOut` fields match the `Focus` type; `suggested.deepest` matches `Outcome.suggested.deepest`.
- Proportion: code appears only as tests, signatures, exact strings and the two rules (compose replacement, open-state default) that the signatures do not determine.
