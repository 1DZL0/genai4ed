# Memory across lessons, activity types, and the prompt overhaul

Written 14 November 2026 and revised the same day after each of Diesel's decisions. Nothing here
is built yet. The order of the work is under "Build order". One local commit per task. Nothing is
pushed.

## Decisions already made

1. **Memory needs no teacher approval.** The researchers decide what goes into it. The teacher
   can see it on the student's card and cannot edit it.
2. **The old question goes away.** "Right answers or open-ended writing" is no longer asked. It
   is filled in from the kind of activity.
3. **A teacher who types without picking an activity box.** What happens depends on what their
   words say:
   - The words name only a topic ("a lesson on fractions"): the agent does not draft. It shows
     the seven headings in the chat and waits for a pick.
   - The words say what the students will do ("an essay on school uniform", or a whole lesson):
     the agent drafts it and works out the heading and the kind itself. The heading it worked
     out is shown highlighted in the chat and marked as a guess, for the teacher to keep or
     change.
4. **The exact kind is worked out and said, never picked.** The teacher sees only the seven
   headings. The kinds are the agent's knowledge and the researchers' coding scheme. They are
   not shown as buttons, in whole or in part. The agent says its guess in one plain line about
   what the students will do ("I'm guessing students solve multi-step equations and explain
   each step. Tell me if you meant something else."). The teacher corrects it by typing.
   Carrying on, or approving the lesson, counts as keeping the guess.
5. **Ask the few that matter.** The agent always asks the lesson length and the students' age
   unless the teacher said them. Everything else it may work out and mark for checking.
6. **The title is proposed, not asked as a blank.** The agent names the lesson and says so in
   its line ("I've called it 'Solving linear equations'. Change it if you like.").

## Build order

Part A comes first, as decided. Parts B and C are woven together, because a live check is only
worth its cost once the prompt's words for it exist.

| Step | Tasks | Then |
|---|---|---|
| 1 | A1 to A8: memory, with its own heading in the tutor's prompt | Go live (see "Going live"), then A9, the real run. |
| 2 | C1: the teacher prompt reordered, same words | |
| 3 | B1 to B6, B9, B10: the list, the lesson's fields, the two boxes, the tutor's line, the demo agent | |
| 4 | B7, B8 with C2 to C5, C12, C13: the back and forth, on the server and in the prompt's words | |
| 5 | C6, C10, C11: the tutor's activity line, the word limit, the cached opening | |
| 6 | B11, B13, B14: tests, the export, the coding guide and the rubric | Go live, then B12 and C9 as one live check. |

C7 is done inside A5. C8 (versions) applies to every step.

## Part A: memory across lessons

**Goal.** A student's later lessons are personalised from their earlier ones, in any subject,
without the tutor reading old conversations.

**What exists today.** Every judged answer and misconception is a row in Postgres. The tutor is
shown up to 8 earlier judgments when the new lesson shares a topic tag, plus a count per topic.
It has never been run as a real series of lessons.

**What the note will look like.** One short note per student, about 100 words at most.

> **How this student learns** (goes into every lesson, any subject)
> - Usually needs two hints before getting a step right.
> - Does better when a worked example comes first.
> - Stops when a question has several parts. Ask one part at a time.
>
> **What this student knows** (goes into lessons in the same subject only)
> - Maths, linear equations: 3 of 5 answers met. Subtracts before dividing.

### Tasks

| # | Task | Done when |
|---|------|-----------|
| A1 | **Run what exists and fix it.** An automated test takes one student through two lessons (no model) and checks what the second lesson's tutor is shown. Fix whatever it turns up. | The test passes and shows the earlier judgments in the second lesson's prompt. |
| A2 | **Match on subject.** Earlier judgments are recalled when the new lesson has the same subject, not only a shared topic tag. The subject's name is made the same first: in the prompt check the agent wrote "Maths" for a lesson that another lesson calls "mathematics". | A lesson tagged "equations" recalls one tagged "algebra" when one says Maths and the other says mathematics. |
| A3 | **The learner note.** A new table in Postgres holding one note per student in the two parts above. Each change is kept as a new version and the latest one is the note. It is deleted with the student. No vector database. | A student has one note that a new lesson updates, never a growing pile. |
| A4 | **The lines worked out from the record.** With no model call: how much help they usually need (hints and tries per step, whether they finish), and what they know per subject. | The note says, for example, "usually needs two hints before getting a step right". |
| A5 | **The lines the model writes.** At the end of a lesson the review call is given the old note and returns the new "how this student learns" lines: three or four at most, none of the student's own words. The lines are information for the tutor, never orders. The server keeps at most four, cuts each to a set length, and drops a line that copies five or more words in a row from what the student wrote, so nothing a student types can ride into later lessons. | Ending a lesson updates the note of every student who took part. A student who types an instruction into a lesson does not get it back as a memory line. |
| A6 | **Into the tutor's prompt.** Under its own heading, "What you know about this student from before", with a line on how to use it. The prompt check showed the tutor reads the memory and does not use it when it is two lines inside "What the platform noticed". The heading sits after the opening every student shares, so that opening stays cached. "How this student learns" goes into every lesson. "What this student knows" goes in only for the same subject. A student with no earlier lessons gets no heading. The note is written for every student, and the study switch (memory on or off) decides only whether the tutor is shown it. Each turn records the lines the tutor was shown. | The research view shows which memory lines each turn carried. |
| A7 | **Seen, not edited.** The student's card shows "What the tutor remembers" as plain text with no buttons. The research view shows it too. | A teacher can read the note and cannot change it. |
| A8 | **Tests.** Automated tests for each task above. | `scripts/check task` passes. |
| A9 | **A real run.** The three review pupils take a second lesson on linear equations. Check whether the tutor picks up the taxi-fare mistake and the blank record unprompted. About ten live tutor turns and one review call. | A short write-up of what the tutor did with the memory. |

**Left out on purpose.** Feelings or character labels, special needs or health, the "possible
cheating" flag, and the student's own words.

## Part B: activity types

**Goal.** The teacher says what kind of activity they are assigning by picking from a short list.
The agent works out the exact kind from what the teacher writes, says its guess to the teacher
in plain words, and finishes the lesson once the teacher keeps or corrects it.

**Research questions this part answers.** Was the system able to understand the teacher's goal
and activity? Was it able to produce a lesson that fits that activity?

**Hypothesis.** Given an optional heading and the teacher's own words, the agent names the
intended activity about as well as a human coder does, and builds a lesson that a researcher
rates as fitting it.

**Why the kinds are not shown.** If the teacher pressed the exact kind there would be nothing
left for the system to understand, and the first question would be answered by how the screen
is built. A part list would be worse than none: a teacher presses the nearest button and the
record says something they did not mean.

**What this design cannot show.** Whether picking a heading helps: the pick is optional, so
teachers who pick differ from those who do not. To claim it, the box would be shown to some
teachers and hidden from others. Whether choosing the kind beats inferring it: kind buttons
would be a second study condition, and the study switch today is per student, so a
teacher-side one would be new work. Neither is planned.

### The list

The teacher sees only the seven headings. The agent is given the kinds under each one, and the
researchers code what teachers asked for with the same list.

| Heading (the teacher picks) | Kinds (the agent infers) |
|---|---|
| Writing tasks | Essay, letter or paragraph writing (each argumentative, narrative or descriptive); creative writing (story, dialogue); summary writing; report writing |
| Mathematics tasks | One-step problems and multi-step problems (word problems, equations, calculations, graphs, diagrams); mathematical reasoning and justification; error identification and correction; data interpretation and analysis; pattern recognition and generalisation; mathematical modelling; comparing and evaluating solutions |
| Open-ended question answering | Short-answer and extended-answer questions (explanation of concepts; comparison and contrast; evidence-based responses) |
| Multiple-choice / Cloze tasks | Multiple choice and fill-in-the-blanks (single or multiple answer selection); true / false questions |
| Reading comprehension | Identifying main ideas; making inferences (bridging, elaborative); comparing multiple texts; evaluating arguments |
| Critical thinking and evaluation | Evaluating claims and evidence; identifying misconceptions; identifying bias; evaluating alternative solutions |
| Scientific inquiry / Investigation | Formulating hypotheses; designing experiments; interpreting experimental results; drawing conclusions from data |

**Two things are mixed in the kinds.** Most clearly under Mathematics: the form of the task
(one-step, multi-step) and the thinking it asks for (reasoning, interpreting data, modelling).
Both stay with the agent. The thinking overlaps with the goal level the lesson already carries.

**The list is not complete and does not need to be.** It is never shown to the teacher as a
menu, so a missing kind blocks nobody. When none fits, the agent names the kind in its own
words and the lesson is recorded as "not on the list", with the words used. Those records show
what the list is missing, and a kind that keeps coming up is added to it (a one-line change, B1).

### The back and forth

| What the teacher did | What the agent does |
|---|---|
| Picked a box and gave only a topic | Drafts a sketch shaped by that heading, with a proposed title. Says its guess at the kind in one plain line. Asks the length and the age. |
| Picked a box and gave a whole lesson | Builds exactly what was given. Says its guess at the kind in one plain line. Adds only the finish lines the teacher left out. Asks the length or the age only if the teacher left them out. |
| No box, and the words name only a topic | No draft. One line asking what kind of activity it is, with the seven headings shown in the chat. It waits. Once a heading is pressed it carries on as in the first row. |
| No box, and the words say what the students will do | Drafts it. Works out the heading and the kind. Shows the heading in the chat, highlighted and marked as a guess, with "change" to open the seven. Says its guess at the kind in one plain line. |
| The box and the words disagree (Writing picked, the words describe a multiple-choice quiz) | Drafts from the words. Names the mismatch in one line. Shows the heading it read highlighted and marked as a guess, beside the one the teacher picked. |
| Several boxes picked | One lesson. Each step carries its own heading and kind. The agent says the kinds in one line. |
| The words fit two kinds about equally | Builds for the likelier one and names the other in a few words ("I could also make this a find-the-mistake task"). |
| Nothing on the list fits | Names the kind in its own words and carries on. Recorded as not on the list. |
| The teacher carries on without speaking to the guess | The guess stands. Recorded as kept without a word. |
| The teacher corrects the kind by typing | Redrafts the steps for that kind. Keeps everything the teacher wrote themself. Recorded as corrected, with the teacher's words. |
| The teacher changes the heading later | Redrafts the steps for the new heading and guesses the kind again. Keeps the title, subject, age, length and everything the teacher wrote themself. |

### What the teacher sees in the chat

The teacher picked Mathematics and typed "linear equations". The reply:

```text
Agent   Here is a sketch of three steps. I've called it "Solving linear equations".
        Change it if you like. I'm guessing students solve multi-step equations and
        explain each step. Tell me if you meant something else.
        1. How long is the lesson?
        2. What age are the students?

        Activity   [ Mathematics ]  change
```

The teacher picked nothing and typed a whole lesson on persuasive paragraphs. The reply ends:

```text
        Activity   [ Writing tasks  guess ]  change
```

- A heading the teacher picked is filled in the site's main colour. One the agent worked out is
  in a second colour and carries the word "guess".
- "change" opens the seven headings.
- No kinds are shown. The guess at the kind is the sentence in the agent's own words.
- Answering the two questions without speaking to the guess keeps it. Typing "no, I want them
  to find the mistakes in worked answers" corrects it.
- Once the lesson is approved, the card shows one line ("Mathematics, multi-step problems")
  with "change" beside it.

### How much the teacher gave

| The teacher gave | The agent builds |
|---|---|
| Only a topic (and a box) | A sketch: a title and two to four step headings with one real question each, shaped by the kind. |
| Part of a lesson | Every word the teacher gave is kept. The gaps are filled and each filled gap is marked to check. |
| The whole lesson | Exactly that. Only what the platform needs and the teacher left out is added (finish lines), marked to check. Nothing is changed. |

### Tasks

| # | Task | Done when |
|---|------|-----------|
| B1 | **The list in one place.** One file on the server holds the seven headings, the kinds under each with their detail, whether each kind has right answers or is judged against criteria, and one line per heading on the shape of such a lesson. The screen, the prompts and the researchers' coding guide all read from it. | Adding a kind is a one-line change. |
| B2 | **Kept in the lesson.** The lesson stores the headings, where they came from (picked before typing, picked in the chat, or worked out by the agent), the exact kind and where it came from (the list, the agent's own words, or the teacher's correction), and what the teacher did with the guess. Lessons made before this still open and run. | An old lesson opens with no heading and works as before. |
| B3 | **The old question removed.** "Right answers or open-ended writing" is filled in from the kind. It leaves the list of things still needed, the tutor settings, and the agent's prompt. | The agent no longer asks it and the settings no longer offer it. |
| B4 | **The box on the teacher's page.** A box with the wording "Select the option(s) that best describe the activity you are assigning." and the seven headings. One, several or none can be picked. Once picked it folds to one line that says the pick and can be opened again. | The picks go with the teacher's next message. |
| B5 | **The activity box in the chat.** The agent's reply can carry it, under the agent's words. With no heading yet: the seven headings to press. With a heading: that one highlighted, with "change" to open the seven. No kinds are shown. A press is sent as the teacher's next message. Only the newest box in the chat can be pressed. A pick and a guess look different, and never by colour alone: a guess carries the word "guess". | Asking for a lesson on a topic with no pick brings up the seven headings in the chat. A whole lesson with no pick comes back with one heading marked as a guess. |
| B6 | **A pick is a fact.** The server reads the pick as pressed. What the teacher pressed outranks what the model says about it. | A model reply that names a different heading does not change the pick. |
| B7 | **The back and forth.** The cases in the table above, each with a test using a scripted model. This is the server's side: reading the pick, recording the case, checking the reply. The prompt's words for the same cases are C2 to C5. | Each row of the table has a passing test. |
| B8 | **What the teacher did with the guess, recorded.** One of three: kept it by saying so, kept it by carrying on or approving without speaking to it, or corrected it (with the teacher's words and the new kind). The first two are kept apart, because carrying on is weaker proof that the guess was right. The model reports whether the teacher's message spoke to the guess, and the server compares the kind before and after. The "guess" mark comes off the card once the teacher keeps it, corrects it or approves the lesson. | The lesson card shows the heading and the kind with no "guess" mark after the teacher approves. |
| B9 | **The tutor's side.** The tutor is told the kind ("The activity is an argumentative essay") and gets one line per heading on how to teach it. | A writing lesson's tutor prompt carries the writing line and a maths lesson's the maths line. |
| B10 | **The demo agent.** The no-model demo agent follows the same flow. | The demo shows the box in the chat for a topic-only message. |
| B11 | **Tests.** Automated tests for the picks, the prompts and the agree or change step. | `scripts/check task` passes. |
| B12 | **A real check.** One live draft for each of a few headings: two with a pick, one with none and only a topic, one with none and a whole lesson, one that fits no kind, one where the box and the words disagree, and one where the teacher corrects the kind by typing. About eight live teacher turns. Run after C5 and together with C9, since it tests the prompt's new words. | A short write-up against the two research questions. |
| B13 | **In the research view and the export.** Everything under "What is recorded for the research". The teacher's messages are also exported on their own, without the agent's guess, for coding. | A researcher can open one file to code and a second to compare with the agent. |
| B14 | **The coding guide and the rubric.** Two short documents, written before any teacher uses the platform: how a researcher codes a teacher's message with the list, without seeing the agent's guess, and the rubric for judging whether a lesson fits its activity. No code. | Both are in `docs/` and Diesel has read them. |

## Part C: the prompt overhaul

The teacher agent's prompt grew one rule at a time. The same matter is now spread across
sections: what to ask is in "How to talk", in "Designing a lesson together" and again in "Three
things every lesson carries". Part C puts each matter in one place.

### The teacher agent's prompt, new order

| Section | What it holds |
|---|---|
| 1. Who you are | As now. |
| 2. Reading what the teacher wants | New. The activity comes first. The seven headings and their kinds. How to say its guess at the kind in one plain line about what the students will do, and the title it proposes. What to do when the box and the words disagree, and when nothing fits. |
| 3. What you may fill in and what you must ask | New. One list (below) in place of the rules now scattered across three sections. |
| 4. Building the lesson | By how much the teacher gave (the table above), shaped by the kind. The steps, the questions, the finish lines. |
| 5. The brief and the rules | As now, minus the activity question. |
| 6. How to talk | As now: one line on what was done, one or two numbered asks, what they can say or press. |
| 7. What goes on the card | As now, plus when to show the activity box in the chat. |
| 8. Running a lesson | As now. |
| 9. Students, the class, and after | As now. |

### What is worked out and what is asked

| Thing | Rule |
|---|---|
| How long the lesson is | Asked unless the teacher said it. Never guessed. |
| The students' age | Asked unless the teacher said it. Never worked out from a year group. |
| The activity heading | Taken from the box. With no box: asked when the words name only a topic, worked out and shown highlighted as a guess when the words say what the students will do. |
| The exact kind | Worked out and said in one plain line about what the students will do. Corrected by typing. Never a question that must be answered, and never a list to pick from. |
| The title | Proposed and named in the agent's line. The teacher's own title is kept word for word. |
| The subject | Worked out, marked to check. |
| Objectives, steps and questions | Drafted, marked to check. |
| What counts as done for each step | Drafted, marked to check. |
| The goal level | Worked out from the kind and the objectives, marked to check. |
| The teacher's own words (questions, steps, rules, material) | Never changed and never dropped. |
| The tutor's rules (when the answer may be given, and so on) | The defaults stand and are read back once. |

### Who decides what

The server is certain about what was pressed. The model is good at reading words. So:

- **The server** decides which case of the back and forth applies whenever it can be read from
  the facts (a box was pressed or not, a lesson is drafted or not) and writes it into a short
  block in each turn's prompt: "Where this lesson stands".
- **The model** judges only what is in the teacher's words: whether they name just a topic or
  say what the students will do, which kind it is, and whether a later message spoke to the
  guess.
- **The server checks the model's reply against the facts.** A reply that drafts a lesson when
  the block said "ask for the activity first" is sent back once, as other broken rules are now.

### Tasks

| # | Task | Done when |
|---|------|-----------|
| C1 | **Reorder, change nothing.** The teacher prompt's sections are moved into the order above with the same words. Its own commit. | Every existing teacher test passes unchanged. |
| C2 | **Section 2 written.** Reading what the teacher wants. | The prompt carries the headings and kinds from the one file (B1). |
| C3 | **Section 3 written.** The one list. The scattered copies are taken out. | Each rule in the table above appears once in the prompt. |
| C4 | **Section 4 rewritten.** Building by how much the teacher gave, shaped by the kind. The teacher's own words for a step are kept in the step's question, which is what the student sees. | A whole lesson given by the teacher comes back with every step and question unchanged. |
| C5 | **"Where this lesson stands".** The per-turn block written by the server, and the check on the reply. | The block names the case and the reply follows it in the scripted tests. |
| C6 | **The tutor's prompt.** The activity line names the kind (B9). The memory heading is already in from A6. | The research page's prompt view shows the kind in the activity line. |
| C7 | **The review prompt.** Asks for the "how this student learns" lines. Done inside A5, not as a task of its own. | The review reply carries them. |
| C8 | **Versions.** Every commit that changes what a model reads raises that prompt's version in the same commit: review-v5 at A5, student-v14 at A6, teacher-v15 at C1, and on from there. Every recorded turn then says which prompt wrote it. | Recorded turns carry the new versions. |
| C9 | **A live before and after.** Three of B12's teacher messages are also sent to the old prompt. Three extra live turns, run with B12. | A short note on what changed in the replies. |
| C10 | **One word limit, and count it.** The tutor's limit becomes one number for each type of step, said once. The server counts the words of every reply and records the count. | The research view shows each reply's word count beside its limit. |
| C11 | **The reply shape goes first.** The reply shape is fixed text, but it is sent after the per-turn text, so it is never read from the cache. It moves into the cached opening of the tutor's prompt, and the teacher agent's fixed opening is cached as well. | A second turn inside five minutes reads the fixed text from the cache, for both agents. |
| C12 | **Each rule in one place.** The notes on the reply shape's fields hold about as much instruction as the prose. Every rule changed in Parts B and C is changed in its field note too, starting with the two notes that carry the old "right answers or open-ended" question. Notes that repeat the prose are cut down to what the field is. | No field note says something the prose no longer says. |
| C13 | **Room in the reply.** The title and the guess are two new sentences in a reply that was 570 of its 600 characters in the prompt check. The read-back of the rules shrinks to a short clause, since the card shows the rules in full. A lesson that needs nothing more gets the title, the guess at its kind and no other ask. If the live check shows replies cut short, the limit is raised. | In the live check (B12 with C9) the whole-lesson reply carries the title and the guess, asks nothing, and no reply is cut short. |

## What the prompt check on 14 November showed

Ten live turns on the configured model: the prompts as they are, and three changes made in
memory only (no code was changed). The prompts word for word, the replies and the script are in
`.superdesign/tmp/prompt-check-2026-11-14/`.

| What was tried | What happened | What it means here |
|---|---|---|
| A teacher names only a topic (twice) | A sketch each time, the two asks, the length and the age left empty, the filled-in parts marked for checking. | The prompt as it is gets followed. |
| A teacher gives the whole lesson | All three steps kept, the teacher's finish line kept word for word, nothing left to ask for. The agent still asked two more questions. | C13. |
| One sentence changed: a topic alone gets the question about the activity (twice) | No draft, nothing on the card, one line asking which of the seven it is. The whole lesson was still drafted, with "I read this as an argumentative paragraph. Is that right?". | The case split in Part B works when written as a rule. The model told the two cases apart. |
| The tutor, a wrong answer, no memory | No answer given away, one question, the slip named, judged not met. 59 words against a limit of 50. | C10. |
| The same with memory as it is written today | The note for the teacher named the earlier lesson. The teaching did not change. | The memory is read and not used. |
| The same with memory under its own heading and a line on how to use it | The question changed to fit the note ("Before any numbers, can you say in words..."). Nothing from the record was read out to the student. | A6 and C6 as planned. |
| The tutor's word limit halved | 59 words fell to 32. The limit was 25. | A change takes effect, and the limit is treated as a rough aim. C10. |

**What this does not show.** Each case ran once or twice, so a rule followed here may not be
followed every time. The middle case (a teacher gives part of a lesson) was not run. The memory
lines in the test were written by hand: whether the platform writes good ones is A4, A5 and A9.

## What is recorded for the research

For every lesson, in the research view and the export:

1. What the teacher picked, and when: before typing, in the chat after being asked, or never.
2. What the agent worked out: the heading and the kind, whether the kind was on the list or in
   the agent's own words, and the sentence it said to the teacher.
3. Whether the agent asked for a pick before drafting.
4. How much the agent judged the teacher to have given: only a topic, part of a lesson, or the whole lesson.
5. What the teacher did with the agent's guess: kept it by saying so, kept it by carrying on, or
   corrected it (with the teacher's words and the new kind).
6. Whether the box and the words disagreed.
7. The first draft, each change, and the approved lesson, kept so a researcher can judge whether the lesson fits the activity.
8. Every kind that was not on the list, with the words used.
9. The title the agent proposed and whether the teacher changed it.
10. The teacher's messages on their own, without the agent's guess, so a researcher can code
    them with the same list before seeing what the agent said (B13, B14).

Items 1 to 6 and 10 answer "Was the system able to understand the goal and activity of the
teacher?": the agent's kind is compared with the researcher's code, and item 5 says what the
teacher made of it. Item 7 answers "Was the system able to produce an activity-relevant
lesson?", judged with the rubric (B14). Item 8 shows what the list is missing, so the list can
grow from what teachers asked for.

Only what teachers typed to the agent is coded. Nothing a student wrote is coded by a
researcher, and no student's words go into the coding files.

## Live model turns

| Where | Turns | For |
|---|---|---|
| A9 | about 11 | The three pupils' second lesson and one review call. |
| B12 with C9 | about 11 | Eight cases on the new prompt. Three of them are also sent to the old prompt, for the before and after. |

Everything else is tested with a scripted model and costs nothing.

## Going live

Twice: after step 1 of the build order (memory) and after step 6 (activity types and the new
prompts). Each time, only when Diesel says so:

1. A backup of the database by hand first. The fix to the automatic backup is still waiting.
2. The database changes applied (A3 adds a table).
3. The server and the web page rebuilt, so the site serves the new code.
4. A check with a review- account before any real class uses it.

Nothing is pushed to GitHub at any point unless Diesel says "push".

## To confirm before real teachers and students

These are Diesel's to answer. None of them blocks building, or testing with review- accounts.

1. The ethics approval and the information sheets cover a note about each student that is kept
   between lessons and shown to the tutor.
2. They cover researchers reading and coding what teachers typed to the agent. Students'
   writing is not coded.
3. How long a student's note is kept, and that it is deleted with the rest of the student's
   record. The daily clean-up task is still waiting to be built.

## Open choices

Each has a default that stands unless Diesel says otherwise.

1. **When the memory lines are written.** Default: when the lesson ends, by itself (one model
   call per lesson). The "Write the summary" button then shows what was already written. The
   other way, only when the teacher presses the button, would make memory depend on a button
   press and muddy the study.
2. **What feeds the memory.** Default: only the record and the model's lines. A line the teacher
   types about a student, and the student's own choice ("example first" or "try first"), are
   left out for now, since teachers do not edit the memory.
3. **The box and the words disagree.** Default: draft from the words and ask.
4. **An eighth box, "Something else".** Default: yes. A teacher who sees no fit has a way to say
   so, and the agent then names the kind in its own words.
5. **Several boxes picked.** Default: one mixed lesson with each step carrying its own kind.
6. **How much the prompt says about each kind.** Default: the names of the kinds plus one line
   per heading on the shape of the lesson. More is added only where the live check shows a miss.
7. **Judging the second research question.** Default: researchers judge the recorded drafts with
   a short rubric. The teacher is not asked an extra question.
8. **Who judges "only a topic".** Default: the model judges it from the words and the server
   records its answer.
9. **A tutor reply over its word limit.** Default: count it and record it, and do not send it
   back. Sending it back would make the student wait for a second model call.
10. **Kind buttons.** Default: none, anywhere (decision 4). Showing them to some teachers and
    not to others would be a second study condition. Possible later, not planned.
11. **Who codes the teachers' messages.** Default: two researchers on a shared sample, so how
    far they agree can be reported beside how far the agent agrees with them. One coder is
    quicker and proves less.
12. **The two looks.** Default: a heading the teacher picked is filled in the site's main
    colour, and one the agent worked out is in a second colour with the word "guess". The
    colours are chosen from the site's palette when B4 is built.
13. **How the title is settled.** Default: the agent's title stands unless the teacher changes
    it, by typing or on the lesson card. It is never asked as a question of its own.
