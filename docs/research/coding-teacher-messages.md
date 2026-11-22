# Coding teachers' messages with the activity list

This guide is for the researchers who code what kind of activity a teacher asked for. You code
from the teacher's words alone. The agent's own reading of the same words is coded separately by
the platform, and the two are compared afterwards. That comparison is how we learn whether the
agent reads teachers well.

## What you code, and what you never code

- You code only what teachers typed to the agent. Nothing a student wrote is ever coded.
- You work from `teacher_messages.csv` in the research export (download it with text). It holds
  each message as the teacher typed it: no line saying what they pressed, and nothing the agent
  said.
- Do not open `teacher_turns.csv` or `lesson_activity.csv` until your coding is finished. They
  hold the agent's guess and what the teacher pressed, and seeing them would bias you.

## The unit

One row of `teacher_messages.csv`: one message. Keep its `message_id` with your codes.

## The four codes for each message

1. **Gave.** How much of a lesson the words give.
   - `topic`: only what it is about ("a lesson on fractions").
   - `part`: some of what the students will do ("they write an essay on school uniform").
   - `whole`: the steps or the questions themselves.
   - `none`: not asking for a lesson (answering a question such as the age or the length, asking
     about a class, approving).
2. **Heading.** One code from the list below, `other` when none of the seven fits, or
   `cannot_tell` when the words name only a topic. Leave it empty when Gave is `none`.
3. **Kind.** The kind from the list under that heading, word for word. When none fits, write the
   kind in your own words and add `(not on list)`. `cannot_tell` when Heading is.
4. **Sure.** `yes` or `no`: whether another researcher would very likely code it the same.

## Rules

- Code the words, not what you think the teacher meant to type.
- When two kinds fit about equally, write both, the likelier first, separated by `/`.
- A message that mentions attached material ("make a lesson from this worksheet") is coded from
  its words alone. Write `material` in a notes column.
- A message that changes an earlier description ("no, I want them to find the mistakes") is coded
  as what it now asks for.
- When unsure, code it anyway and put `no` under Sure.

## Agreement

Two researchers code the same fifth of the messages, chosen at random, without talking. Work out
agreement on Heading and on Kind (Cohen's kappa). Talk through every disagreement and agree a
code, but keep both original codes in the file. Then one researcher codes the rest.

## Comparing with the agent, afterwards

Join your codes to `teacher_turns.csv` on `message_id`. For each message, sort the pair into one
of: the same heading and kind; the same heading, a different kind; a different heading; the agent
asked for the activity (`asked_for_activity` is True) where you coded `cannot_tell`; the agent
asked where you could tell; the agent drafted where you coded `cannot_tell`. `lesson_activity.csv`
then says what the teacher pressed, whether the box and the words disagreed, and what the teacher
did with the agent's guess (kept it by saying so, kept it by carrying on, or corrected it).

From 19 November 2026 a teacher can no longer press a heading: the agent asks for an objective,
the age and the length, and guesses the kind of activity from the teacher's words. So rows from
then on have `asked_for_activity` False and an empty `pressed`, and a lesson's `picked` is empty.
The `stands` column in `teacher_turns.csv` names what the server told the agent: on older rows
`nothing pressed`, `pressed`, `answered` or `follow-up`; on newer rows `follow-up`, `not drafted`
or `drafted`. The `prompt_version` column tells the two apart: rows from `teacher-v27` on are
from after the change.

## The list

The same list the teacher's screen, the agent's prompt and this guide come from (the platform's
activity file). "Right answers" and "judged against criteria" say how the tutor judges the
students' work; you do not code them.

**Writing tasks** (code `writing`). Such a lesson: a brief for the piece, then a plan, a draft and a revision; each finish line says what the writing must show.

- essay writing (argumentative, narrative or descriptive): judged against criteria
- letter writing (argumentative, narrative or descriptive): judged against criteria
- paragraph writing (argumentative, narrative or descriptive): judged against criteria
- creative writing (a story, a dialogue): judged against criteria
- summary writing: judged against criteria
- report writing: judged against criteria

**Mathematics tasks** (code `maths`). Such a lesson: a way in, then problems that get harder; each step has an answer or a justification to judge against.

- one-step problems (word problems, equations, calculations, graphs, diagrams): right answers
- multi-step problems (word problems, equations, calculations, graphs, diagrams): right answers
- mathematical reasoning and justification: judged against criteria
- error identification and correction: right answers
- data interpretation and analysis: right answers
- pattern recognition and generalisation: right answers
- mathematical modelling: judged against criteria
- comparing and evaluating solutions: judged against criteria

**Open-ended question answering** (code `open_questions`). Such a lesson: a few questions that ask for an explanation, a comparison or evidence, each with what a good answer must include.

- short-answer questions (explaining a concept, comparing and contrasting, answering from evidence): right answers
- extended-answer questions (explaining a concept, comparing and contrasting, answering from evidence): judged against criteria

**Multiple-choice / Cloze tasks** (code `choice`). Such a lesson: short questions with options or blanks, each with its right answer and why the tempting wrong ones are wrong.

- multiple choice (one answer or several to select): right answers
- fill-in-the-blanks: right answers
- true / false questions: right answers

**Reading comprehension** (code `reading`). Such a lesson: the text first, then questions that go from what it says to what it implies; each answer points back to the text.

- identifying main ideas: right answers
- making inferences (bridging, elaborative): right answers
- comparing multiple texts: judged against criteria
- evaluating arguments: judged against criteria

**Critical thinking and evaluation** (code `critical`). Such a lesson: a claim, an argument or a set of solutions to weigh, then steps that ask for a judgement and the grounds for it.

- evaluating claims and evidence: judged against criteria
- identifying misconceptions: right answers
- identifying bias: judged against criteria
- evaluating alternative solutions: judged against criteria

**Scientific inquiry / Investigation** (code `inquiry`). Such a lesson: a question to investigate, then a hypothesis, a plan or some results to read, and a conclusion tied to the evidence.

- formulating hypotheses: judged against criteria
- designing experiments: judged against criteria
- interpreting experimental results: right answers
- drawing conclusions from data: right answers

**Something else** (code `other`). None of the seven fits. Write the kind in your own words.
