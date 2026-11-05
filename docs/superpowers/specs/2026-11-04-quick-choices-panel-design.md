# Quick choices on the create screen, and depth as a switch

Date: 4 November 2026. Status: revised after builder check; awaiting approval.

## Intent

A teacher writing a lesson should find the tutor's rule switches on their own, from the first screen, without anyone telling them they exist, and the class agent should point to them in its own words. One of those switches is depth: how deep the tutor pushes a right answer, on the 1 to 4 scale the platform already uses (Webb's Depth of Knowledge). The end-of-lesson summary should then report how deep each student actually got, so the switch has a visible effect.

Why now: the current "Quick choices" box already holds the right content (task type, question style, level, help while working, what happens at the end, tone, what interrupts the teacher) and already works the way the project wants: the choices become a sentence the agent reads, and the rules are compiled from words. Its faults are placement and visibility: it sits on the lesson card, collapsed behind a `<details>` header, and only after the agent has drafted something. Teachers never see it when it would help most. This is also on camera in every teacher shot of the demo video.

## Goals

- The choices are visible under the typing box from the first screen ("What do you want to teach?"), before any lesson exists, and stay under the box once the conversation has begun.
- The agent's own read-back is the entry point: one sentence in the tutor's voice, with the values a teacher most often changes made tappable.
- The full panel of groups opens from that line ("Show all the quick choices") and is open by default on a teacher's first visit.
- "Level" becomes the depth switch: four rungs labelled 1 to 4 in plain words, default 2, and the choice reaches the tutor as the depth for the lesson.
- At depth 3 or 4 the tutor asks up to twice for the missing depth before moving on. It never traps a student.
- The end-of-lesson summary shows, per student, the deepest rung they reached, in the same words the switch uses.
- When the agent drafts or changes a lesson, it reads the rules back in one sentence and says the quick choices under the box change any of them.
- One control, not two: the lesson card keeps its read-only pills; the panel lives under the box.

## Non-goals

- No new API for setting rules directly. Words stay the channel to the agent. This keeps every rule a variable in the prompt rather than a hard-coded gate.
- No change to what a rule change means mid-lesson (an approved lesson still needs re-approval; teacher guidance in the chat still outranks the rules).
- No change to the student-facing prompt or the review prompt's depth vocabulary. The engine stays Webb 1 to 4 with its current words; the UI adopts them.
- No redesign of the rest of the teacher page. Teaching approaches are gone from the teacher side and stay gone.

## Anti-goals (what would make this a failure even if it works)

- A control that is only reachable by expanding something. The sentence must be visible with no interaction.
- Server-side enforcement sneaking back in. The depth switch changes the prompt and the summary; it must not add a gate.
- A read-back that drifts from the lesson's real rules, or from the defaults in `policy.py` before a lesson exists.
- A depth word shown to the teacher that means something different to the tutor.
- Em or en dashes anywhere in the UI text.

## What exists (the builder starts from this)

- `frontend/components/cards/lesson.tsx`: `CHOICES` (seven groups) and `QuickChoices({ say, busy })`. Its button is "Tell the agent": it calls `say(sentence)`, which the teacher page wires to `send(words)`, so a press posts to the agent at once and the agent changes the lesson and says what it did. Rendered on the card only when `say && !approved && !card.live`, inside a collapsed `<details>`. The card also has `DEPTH_WORDS` for its step chips.
- `frontend/app/teacher/page.tsx`: the create screen's blank state (heading, composer, three `STARTERS`) and the conversation state (composer under the thread). `send(external?)` accepts words from outside the box. On a phone the card and the conversation are separate tabs.
- `frontend/components/chat.tsx`: `TutorFace` (the pencil), reusable for the read-back row.
- `backend/app/agent/policy.py`: `PolicyRules`, `from_teachers_words` (literal parsing; today it runs on the model's `rules_text`, see `thread.py`), `labels()` (the card's pills), `describe()`.
- `backend/app/agent/brief.py`: `DOK_WORDS` (1 to 4, Webb), `DOK_DEFAULT = 2`, `Step.target_dok`, and `Step.depth`, a property with no access to the lesson's rules.
- `backend/app/agent/thread.py`: the teacher-side agent's prompt. It currently tells the model to give every step a target depth from its goal (so `target_dok` is almost always set), lists "level" under `strategy` rather than `rules_text`, still mentions "the approach tiles under the starters", says nothing already on the card goes in the reply, and has `_RULE_WORDS` (no "depth") used by `_drop_carried_rules`.
- `backend/app/agent/scaffold.py`: `step_block` reads `step.target_dok or DOK_DEFAULT`; `TEACH` says a right answer below target gets one ask, then move on; `noticed_block` says "do not ask again" after one depth ask.
- `backend/app/agent/cards.py`: marks a step `depth_set` when `target_dok` is not None and shows "the usual depth" otherwise.
- `backend/app/agent/classroom.py`: `REVIEW_SYSTEM` and the review output with `depth_note`; assessment records carry `depth_shown` and `target_dok`.
- `backend/app/agent/alerts.py`: `ALWAYS_TOLD` (wellbeing, asked_for_teacher).
- `backend/app/routers/thread_lessons.py`: `start_approach` / `set_approach` still exist with no frontend caller.

## Decided

### The read-back row, in both states of the teacher screen

Under the composer, in the blank state and in the conversation state alike, a read-back row: the pencil face, then one sentence in the tutor's voice.

Before a lesson exists it states the defaults:

> Unless you say otherwise, I'll give hints any time, a worked step after 1 wrong try, never the answer, and teach to depth 2, apply it or explain it. I'll tell you at once about a student who's upset or asks for you. Tap any of those to change it, or show all the quick choices.

Once a lesson exists it states that lesson's actual rules, built from the same labels the card's pills use (`help.pills`, `help.at_once`, the depth), so the row and the card can never disagree.

The tappable values are the worked-step rule, the answer rule, the depth, and the "tell you at once" list. Tapping one opens the panel with that group in view and focused; a choice is then one more tap. "Show all the quick choices" toggles the full panel. The panel is open by default until the teacher has at least one lesson, collapsed by default after that; the state is remembered per browser (`localStorage`, read and written inside try/catch; the screen must work if storage is unavailable).

The defaults are a single frontend constant mirroring `PolicyRules` defaults and `ALWAYS_TOLD`, with a comment naming `policy.py` as the source of truth.

### What a press does (my call)

- With no lesson yet: the composed sentence is put into the box, appended after whatever the teacher has typed, and the box takes focus. Nothing is sent until the teacher sends, so the topic and the rules go to the agent together. Pressing the same option again removes it and recomposes.
- Once a lesson exists: the press sends at once, exactly as "Tell the agent" does today, and the agent changes the lesson and says what it did. On a phone this keeps the result where the teacher is looking.

### The panel's groups (my call)

The existing seven groups, with one restructured so the sentence's tappable values each lead to a real choice. "Help while working" becomes three single-pick rows:

- Hints towards the answer: on (default) / off.
- A worked step: straight away / after 1 wrong try (default) / after 2 / after 3.
- The answer itself: never (default) / after 2 wrong tries / if they ask.

The other groups are unchanged, except "Level", below.

### Depth as a switch

- The "Level" group is renamed "How deep" with options `1 · recall it`, `2 · apply it or explain it`, `3 · justify it`, `4 · take it further`. These are the tutor's own `DOK_WORDS` in plain form, so a teacher's words and the tutor's judgments mean the same thing; the student prompt and the review prompt are not changed (my call: no prompt version bump mid-study for a wording tidy). The card's `DEPTH_WORDS` is replaced by this one shared vocabulary.
- `PolicyRules` gains `depth: int` (1 to 4, default 2). It is the lesson's depth. `from_teachers_words` takes "depth N" and the four rung phrases literally, and the brief writer is told to fill `rules.depth` from the same phrases and to put a depth sentence in `rules_text`, so the literal parse sees it whichever route it takes.
- Per-step targets become the exception, not the rule (my call, so the switch actually does something): the teacher agent's prompt changes to set a step's `target_dok` only when the teacher named a depth for that step; otherwise it is left empty and the step takes the lesson's `rules.depth`. A named step keeps its own depth whatever the switch says. `Step.depth` therefore needs the lesson's rules; change its signature and its call sites (five today) rather than keep a property that cannot see them. `scaffold.step_block`, the card's `depth_set` chip and "the usual depth" wording, the "later steps at least as deep" rule, and the Decided bullet all read the effective depth.
- `labels()` adds a pill ("Teach to depth 2, apply it or explain it") and `describe()` a sentence.
- `scaffold.TEACH`: at depth 3 or 4, ask up to twice for the missing depth after a right answer, then move on whatever they give; at 1 or 2, once, as today. `noticed_block`'s "do not ask again" becomes target-aware to match. `TEACH` is fixed prose hashed into the prompt version, so this is a new tutor prompt version; that is accepted, because it is a behaviour change, not a wording tidy.

### The summary

The review output gains, per student, the deepest depth shown across their judged answers (a maximum over recorded `depth_shown`, computed by the server from the model's own judgments: an aggregate of the model's calls, not a new inference). The outcomes card shows it beside each student in the shared vocabulary ("Deepest: justify it"). The research view may show the number; optional.

### The agent points to it

The teacher-side agent's prompt gains one instruction: after drafting or changing a lesson, read the rules back in one plain sentence (hints, worked step, the answer, depth, what interrupts the teacher) and say that the quick choices under the box change any of them. This sentence is an explicit exception to "nothing already on the card goes in the reply". The agent must not claim to have changed a switch itself. The mention of "the approach tiles under the starters" is removed; teaching approaches are dead on the teacher side and the defaults constant stands.

### Look

Project tokens only: paper, sheet, rule, ink, pencil, progress. The read-back row matches the approved mockup (option C in the brainstorm): white row, pencil face, tappable values as ink text on a `progress-wash` background with a `progress` underline. The panel keeps today's pill buttons and fieldsets. Fonts and spacing unchanged.

### Accessibility

Fieldsets with legends as today; every tappable value is a `<button>` with `aria-pressed` where it toggles; the panel is keyboard reachable in order; the read-back sentence is plain text to a screen reader with the values announced as buttons. Focus moves to the opened group when a value is tapped. The row wraps at 420px and the panel's button rows scroll sideways.

## Constraints

- Next 16, React 19, Tailwind v4 with the tokens in `globals.css`. Frontend checks are `tsc --noEmit` and `eslint`; there is no frontend test runner.
- Backend tests are pytest against Postgres (`uv run pytest`), 293 passing today; `conftest.py` forces enforcement on for the suite.
- Pseudonyms only in any example text. No real names.
- `.superpowers/` and `.superdesign/tmp/` are scratch, not product.

## Builder notes (from the check, to be handled in the build)

- `_RULE_WORDS` in `thread.py` needs "depth", or a lesson whose only rule is a depth sentence loses it to `_drop_carried_rules`.
- `from_teachers_words` should also run on the teacher's own message for the depth phrases, not only on the model's `rules_text`.
- The read-back row in the conversation state changes the composer area's layout; keep the composer's own height logic intact.

## Tests the builder must add

- `from_teachers_words`: "depth 3" and "students should justify it" set `depth = 3`; a sentence with no depth leaves the default.
- `PolicyRules.labels()` and `describe()` include the depth.
- A step with no named depth takes `rules.depth`; a step with a named depth keeps it.
- Review: deepest depth per student is the maximum of their `depth_shown`, and absent for a student with no judged answer.
- Scaffold: at depth 3 the TEACH text says up to twice; at depth 2 it says once.
- Frontend: typecheck and lint clean; a manual check at 420px.

## Left to the builder

- Component boundaries and file names (for example `components/quick-choices.tsx` holding `CHOICES`, the panel, the read-back row, and the shared depth vocabulary).
- The exact micro-interaction when a value is tapped, within the one-more-tap rule.
- The `localStorage` key name; "first visit" is "no lessons in the teacher's list".
- Wording polish of the sentence and the pills, within the no-dash rule.
- Whether the defaults constant is later replaced by an endpoint.
