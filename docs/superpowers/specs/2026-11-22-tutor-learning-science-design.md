# Tutor guidance from learning science, measured old against new

Date: 22 November 2026. Diesel's decisions the same day: everything goes in as guidance the
agent applies with judgement, never a rule the server enforces; depth of knowledge goes into
the agent and, as a hint, into lesson drafting; build it, commit it, then measure the new
prompts against today's on situations aimed at each change.

## Why

A colleague reviewed the tutor's prompts and raised six points (A to F): the tutor may confuse
engagement with learning; adaptation has no criteria for choosing what to change; language
difficulty is not low understanding; struggling students risk getting less demanding work;
lack of learning is not lack of engagement; supported success is not independent learning.

Correction to what was said on 22 Nov: depth of knowledge is not in today's prompts. It was
replaced by Bloom's levels in October (v12), and those were taken out on 15 Nov (v19, commit
1aca6d4) "until the redesign". This is that redesign, with depth of knowledge, not Bloom.

## Goals

1. Each change shows in the tutor's replies on a situation built for it.
2. The difference is measured: today's prompt and the new one, same situations, same model,
   several runs each, judged blind.
3. Nothing that works today gets worse: the teacher test set and the backend tests still pass.

## Non-goals

- No server-enforced rules, gates or thresholds. The tutor decides; the platform records.
- No Bloom's taxonomy (Diesel chose depth of knowledge).
- No new screens. No deploy until Diesel has seen the measured results.
- No change to what the teacher decides (help rules, approval).

## The changes

Tutor, in "How to teach" (sent on every turn, so they hold with adapting on or off):

- **T1 Why it is wrong.** On a wrong or partial answer, form a view of the cause: missing or
  wrong knowledge (a misconception), a reasoning slip, or trouble putting it into words. The
  assessment gains one optional field, `error_kind` (knowledge, reasoning, expression), so the
  choice is recorded. Recorded only; nothing acts on it. (My call: a field rather than a note,
  so it can be counted.)
- **T2 Supported is not yet independent.** A step met with hints or a worked step is progress,
  not yet mastery: where the step allows it, follow with one brief comparable question done
  without help, and fade the help on the next question rather than repeating it.
- **T3 What usually fits.** The cause guides the response, as what usually works, not a rule: a
  misconception wants refuting and a reason why; overload wants one part at a time; a gap
  wants the missing piece first; a reasoning slip wants a worked example or smaller steps; a
  wording difficulty wants another way to show it. Judge from their next reply whether it
  worked, and change course if not.
- **T4 Language is not understanding.** Match the words to how they read and write, separately
  from the thinking asked of them; a short or clumsy answer is not a shallow one. Keep the
  subject's own key terms.
- **T5 Support, not less demand.** A student who is struggling gets more support towards the
  same thinking before they get an easier question. Every student gets the chance to explain,
  compare and judge.
- **T6 Switched off is not stuck.** When a student seems disengaged, a brief check-in on how
  they are, and no drop in demand because of it. Interest comes from something concrete, a
  picture in words or a choice, inside the lesson's own content.
- **T7 Depth of knowledge.** Four kinds of thinking: recalling, applying a skill or idea,
  reasoning strategically (explain, compare, justify), extended thinking (connect, design,
  evaluate over time). Vary them in the subject's own ways, not as a ladder of difficulty.
  The pitching block's "Reasoning" and "Judgement" changes point to it.

Class agent:

- **C1 Depth across the steps.** When drafting, vary the kind of thinking across the steps,
  in the subject's own terms, so the lesson does not stay at recall. Guidance, not a quota.

## How it is measured

- **Harness:** `backend/bench/tutor_ab.py`. Each situation is seeded in a scratch database
  (`genai4ed_ab`) with the app's own models: a lesson, the teacher's rules, adapting on or off,
  memory lines where needed, and a short scripted list of student messages driven through
  `StudentAgent.respond` with the real model. Transcripts and reply fields are saved.
- **Judge:** each situation has one or two plain criteria. A different model
  (`anthropic/claude-sonnet-5.5`, my call, so the tutor does not grade itself) reads the
  transcript without knowing which prompt wrote it and answers pass or fail with a reason.
  Fields from the records (`error_kind`, `pitch_call`, `judgment`) are counted directly.
- **Old against new:** the harness is committed first; today's prompt runs from a git worktree
  at that commit, the new prompt from the working tree. Three runs per situation per version.
- **Report:** one table, situation by criterion, old pass rate against new, with the reasons.
- **Teacher side:** a teacher-set case for C1 run on both versions; the full teacher set and
  the backend tests on the new version.
- **Cost:** about $8 to $12 of model calls in all.

## The situations

| # | Targets | Situation | Pass when |
|---|---|---|---|
| 1 | T1, T3 | Fractions: answers 1/3 + 1/4 = 2/7 | Names the wrong idea (adding tops and bottoms) and gives a reason or counter-example; error_kind knowledge |
| 2 | T1, T3 | Equation 2x + 5 = 19, answers 2x = 24 | Points to the exact step that went wrong; error_kind reasoning |
| 3 | T1, T4 | Science "why does ice float", clumsy English with the right idea | Treats the idea as there, helps with the wording, keeps the demand; error_kind expression |
| 4 | T2 | Gets a step right after two hints | Follows with a comparable question done without help, or fades the help |
| 5 | T5 | Adapting on; memory: needs help twice, finished 0 of 3 | Keeps the step's thinking, with support up front, not an easier question |
| 6 | T6 | "this is boring", "whatever" | A brief check-in; no drop in demand |
| 7 | T4, T5 | Adapting on; memory: right first time, reads in a second language | Plainer words, same or higher thinking (still asks why) |
| 8 | T3 | "there's too many bits I don't get it" on a multi-part question | One part at a time |
| 9 | T7 | Adapting on; strong student, recall step | Raises the kind of thinking (explain, compare, justify), not just harder numbers |

## Left to the builder

The exact sentences, kept short and in the prompts' plain style; how memory lines are seeded;
the judge's wording; how runs are laid out on disk.
