# Moving between steps

Agreed in conversation on 6 November 2026.

## Why

A pupil who is stuck on a step today stays on it until the tutor accepts an answer, the
tutor gives up under the rules, or the teacher steps in. They cannot go on and come back, and
they cannot change an answer once the tutor has moved them on. Teachers want pupils to be able
to leave a question for later, as on an exam paper, and the record to keep every attempt.

## What a pupil can do

- Press **Come back to this later** on the step they are on. The step is parked and they move
  to the next step not yet done. The tutor is told on the next turn that they just arrived,
  leaving a step for later, and opens the new step.
- Tap a step in the strip at the top to go to it. In order (the default) they may go to any
  step they have already opened and to the next undone step; freely (a teacher setting) to
  any step.
- Go back to a done step and write again. The record keeps every attempt. The judgment that
  counts is the last one given on a return, and the step is marked as changed.
- The lesson finishes when every step is met. Meeting the last step with a parked step
  behind it sends them back to the parked one.

## What the tutor is told

- Each turn is still one fresh call built from the record. When a pupil has moved around, the
  conversation the tutor sees is this step's messages (tagged by step) rather than the last 30
  of everything, and the data block carries each step's status so it knows what else happened.
- A "Right now" line says they just came back to a part-done step, or just moved on leaving
  one for later.
- After two wrong tries, when another step is undone, the tutor is told the button exists and
  may offer it in a short clause.

## The record

- `LearningState.steps[i]` gains `parked`, `wrong` (wrong tries on that step, restored on
  return), `returns`, `arrived` (consumed by the next turn), `changed`, `skipped` (moved on by
  the teacher without a met answer).
- Student messages carry `step_index` in their data, as agent replies already do.
- A move writes a step_change evidence record (`parked`, `returned`, `jumped`) and an event
  line the pupil sees. Leaving a step clears an open struggling alert about it, marked as
  cleared by what they did next, as moving on already does.

## The teacher

- A rule `free_movement` (default false), set from the tutor settings group "Can pupils move
  between steps?" or the sentences "Pupils move in order." / "Pupils move freely between
  steps." The card's pills show "Move freely" only when set.
- Nothing new interrupts the teacher.

## Not in this change

- Answer-only steps accepted without the tutor.
- Previous and Next buttons as such: the strip and the park button cover it.
