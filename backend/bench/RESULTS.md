# Prompt bench results

What the bench showed when the three student prompts were run against the same scripted class,
and why only the structured prompt with depth (v10) remains in the code.

## The runs

Run on 22 October 2026 from this machine, against the local containers.

| | |
|---|---|
| Tutor model | anthropic/claude-opus-5.5 through OpenRouter |
| Pupils' words | anthropic/claude-sonnet-5.5, from a persona and a fixed beat plan |
| Pupils | six: steady, struggling, answer_seeker, anxious, bare, minimal |
| Turns | up to 8 each, the same plan on every run |
| Lesson | "Bench: Percentages of amounts", three steps, teacher bench-t |
| Tutor calls | 53 in each run |
| Supervisor | on, every check enforced |

The three prompts:

- **v8**, `student-turn-v8`: the earlier prose prompt, with the lesson and the student's position
  sent as one JSON block.
- **v9**, `student-v9-40e5b9e4`: the structured prompt (fixed prose, four server-filled blocks,
  one data block) without the depth of knowledge lines.
- **v10**, `student-v10-213b03ac`: the same with depth: each step carries a target depth from 1
  to 4, the tutor reports the depth the student showed, and a right answer below the target is
  asked for its why once.

## The numbers

| measure | v8 | v9 | v10 |
|---|---|---|---|
| tutor calls | 53 | 53 | 53 |
| mean reply, s | 8.4 | 9.7 | 10.8 |
| words a reply | 67.0 | 78.1 | 75.6 |
| answers given away | 0 | 0 | 0 |
| first-draft conflicts | 0 | 0 | 0 |
| held back | 0 | 0 | 0 |
| hints | 23 | 16 | 20 |
| worked steps | 5 | 3 | 4 |
| exactly one question | 50 | 50 | 48 |
| no next action | 0 | 0 | 0 |
| markup | 0 | 0 | 0 |
| repeated reassurance | 3 | 1 | 4 |
| right judged right | 26/27 | 27/27 | 26/27 |
| wrong judged wrong | 7/7 | 7/7 | 7/7 |
| attempt flag right | 43/45 | 43/45 | 42/45 |
| depth under/aligned/over | 0/0/0 | 0/0/0 | 13/21/1 |
| finished | 1 | 1 | 1 |
| steps reached, mean | 1.83 | 2.0 | 1.5 |
| alerts | misconception_pattern 1, safeguarding 1, struggling 6, teacher_requested 1 | the same | struggling 5, the rest the same |
| errors | 0 | 0 | 0 |

"Right judged right" counts the tutor's judgment on the beats where the pupil's plan said the
answer was right; "attempt flag right" counts whether the tutor correctly said if the message was
an attempt at all. The depth row is only measured by v10.

## What it means

All three prompts kept the answer back on every one of the 53 calls, passed every enforced check
on the first draft, and judged right and wrong answers almost perfectly. On those measures the
rewrite from prose to structure cost nothing and gained nothing.

What v10 adds is the depth measure. Of the 35 right answers it judged, 13 came in below the
step's target depth (the number without the method, or the method without the why). That is the
signal the other two prompts cannot see, and it is the one the teacher's outcomes card now
reports.

The price is pace. v10 reached fewer steps in the same number of turns (1.5 against 1.83 and
2.0) and took longer per reply, because it stops to ask for the why. After this bench the server
started counting how many times the tutor has asked for depth on a step and telling it not to
ask again once it has. That change was not re-benched.

## The decision

v10 stays. v8 and v9 were removed from the code on 22 October 2026, along with the setting
that chose between them. Every recorded turn keeps its `prompt_version`, so the research view
still says which prompt wrote it. The last commit that still holds all three prompts is
`d15f033`; check it out to re-run the comparison.

## Running the bench again

The bench now runs against whatever prompt is deployed and records its version:

    uv run python -m bench.run_bench --label v11 --out bench/out/v11.json
    uv run python -m bench.run_bench --compare bench/out/v10.json bench/out/v11.json

The raw outputs of the runs above (`bench/out/v8.json`, `v9.json`, `v10.json`) are on the
development machine and are ignored by git.

## 23 October 2026: one sentence added to the prose

The pupil's page now keeps the current task on screen above the box they write in, so the
prose gained one sentence: the closing question can be short and need not restate the whole
problem. The version became `student-v10-81d8b355`. The same six pupils, 53 calls:

| measure | v10 (22 Oct) | v10 (23 Oct) |
|---|---|---|
| answers given away | 0 | 0 |
| first-draft conflicts | 0 | 0 |
| words a reply | 75.6 | 73.4 |
| exactly one question | 48 | 43 |
| right judged right | 26/27 | 27/27 |
| wrong judged wrong | 7/7 | 7/7 |
| depth under/aligned/over | 13/21/1 | 16/19/0 |
| steps reached, mean | 1.5 | 1.67 |

Nothing given away, judgments as good or better, replies a little shorter. Fewer replies end
in exactly one question, which is the sentence doing what it says. The 22 October run raised
a safeguarding alert from the anxious pupil's "stressed" line and this run did not: the prose
on wellbeing did not change, so that is run-to-run variation to watch, not a regression.

## 15 November 2026: the teacher's prompt in modules, and a test set for it

This section is about the other agent: the one the teacher talks to. Its prompt was one long
text of 15,551 characters (`teacher-v24`), much of it lists of things never to do. It is now
six short modules with worked examples, 6,486 characters (`teacher-v25-386e2b6a`), in
`app/agent/teacher_prompt.py`. Bloom's taxonomy is out of both.

### The test set

`bench/teacher_cases.py` holds 50 realistic teacher messages. Each one is sent to the real
model with the class in a known state, and the reply is checked against named rules.

| group | cases | what the teacher is doing |
|---|---|---|
| new | 15 | asking for a lesson from nothing: a topic, a full description, their own questions, pasted text, Greek |
| pressed | 4 | the same, with an activity heading pressed |
| focus | 19 | working on a lesson that exists: answering a question, changing it, approving, asking to start |
| class | 12 | a lesson is running or has ended: who needs me, how are they doing, end it, keep an eye on someone |

There are 27 rules (`RULES` in the same file), such as "the length and the age come from their
words or are asked, never guessed" and "say only what the class data shows". Every check names
the rule it checks, so a failed run says which rules the prompt is missing.

### The runs

All on anthropic/claude-opus-5.5 through OpenRouter, 14 and 15 November 2026.

| run | prompt | cases that passed | spend |
|---|---|---|---|
| v24 | the old prompt | 41 of 49 | $1.44 |
| bare | "Who you are" and nothing else | 20 of 49 | $1.44 |
| v25a | first draft of the modules | 48 of 49 | $1.51 |
| v25 | the modules as they are in the app, every case twice | 49 of 50 | $2.61 |
| gave | after the fix below, 4 cases three times each | 4 of 4 | $0.66 |

Against the old prompt, v25 passes eight cases that failed and fails one that passed. Seven
old replies were over 600 characters and none are now; the median reply went from 462 to 324
characters. A teacher who gives only a topic is now asked what kind of activity they want.
Every reply was valid on the first try in every run.

The one v25 failure was a teacher who gave two questions and said "build the rest around
them". The lesson kept both questions, but the reply called what the teacher gave "whole"
when it was "part". The note on that field now says what each word means, and the case passed
three times out of three.

### Why each module is there

A module stays only if replies failed without it. Two ways of seeing that were used: the bare
run, with every module out at once, and runs with one module out (`--prompt without:<module>`),
each case twice.

| module | how it was seen | what failed without it |
|---|---|---|
| The activity | bare run | the kind of activity was wrong or missing in 10 cases |
| Age and length | bare run | "Year 9" was turned into an age in 1 case |
| How to talk | bare run | 20 replies too long or not plain talk; 4 asked for more when the lesson needed nothing |
| Starting and ending | on its own | asked to end the lesson in words, both replies failed to point at the End button (one sent the teacher to the wrong place) |
| The class | on its own | 3 of 12 cases: it promised to watch a student and sent their tutor a message nobody asked for (twice), left out the offer of a follow-up (twice), named a student who was fine (once) |

**Age and length is not confirmed.** With only that module out, the 12 cases that ran passed
both times, the year group case among them, because the Year 8 example in "How to talk" shows
the same thing. Eight cases did not run. If they pass too, the module comes out.

**Not yet run:** "The activity" on its own and "How to talk" on its own, the eight cases
above, and a full pass after the fix to the field note. The OpenRouter key reached its $150
limit partway through; the runs that failed for that reason are not counted.

### What was cut

None of these was in the bare run's failures, and the set passes without them: what a lesson
of each kind looks like, the list of what the agent may fill in, how to build a lesson, the
brief and the rules, what goes on the card, reading every rule back to the teacher, the list
of signals and board colours, and most of the section on running a lesson.

### Fixes the set found outside the prompt

- A reply that asks "shall I end it?" was struck as if it claimed to have ended the lesson.
  A sentence ending in a question mark is no longer a claim.
- "Didn't start" now counts as not started.
- The note on the `do` field offered "run" and "end", so the model used them when a teacher
  asked in words. It now offers only approve, pause and resume.

### What the set does not test

Two kinds that fit a request equally well, offers made from a teacher's material, confirming
outcomes and marks, how good a draft is for each kind of activity, and whether "Who you are"
is needed (every run had it).

### Spend and running it again

Measured spend for all of the above, with the small trial runs between: $12.11. A full pass of
the 50 cases costs about $1.30 to $1.50.

    uv run python -m bench.teacher_set --label v26 --against v25
    uv run python -m bench.teacher_set --prompt without:talk --only new,pressed --repeat 2 --label without-talk

The database the set uses is emptied at the start of every run, so run one at a time.
