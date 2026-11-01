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
