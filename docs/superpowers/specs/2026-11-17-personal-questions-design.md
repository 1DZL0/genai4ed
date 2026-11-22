# Same objectives, personal questions

Written up on 17 November 2026 from the conversation with Diesel. Diesel gave the word to start
building that evening. The plan for the first part is
`docs/superpowers/plans/2026-11-18-settings-planning-card.md`. Nothing is committed, pushed or put
on the live site without Diesel's word.

**(Diesel)** marks a decision Diesel made. **(my call)** marks a choice made while writing this
up, for Diesel to check; these are listed again near the end. Lines with neither mark follow
from the two.

## In short

- The agent is a teaching assistant. The teacher delegates work to it and stays in charge.
- A teacher plans a lesson by saying what the students should be able to do by the end. The
  agent asks for what is missing. It does not invent a lesson from a topic alone.
- Each objective gets a short question ladder on the lesson card: an easier step, the baseline
  and a deeper question. The teacher sees all three before the lesson.
- Every student answers the baseline, and only the baseline counts. What the tutor knows about
  a student changes the route: the setting a question is told in, the examples the tutor
  builds, and whether the easier step or the deeper question is used.
- The teacher sees what each student was really asked, with a tag for the route, and has a
  switch for each part in a new Settings tab. For the accounts that exist today, everything
  new is off until switched on.
- It is built and checked on the test copy first, then put on the live site before Athens,
  because people who see it there will ask to use the platform. (Diesel) Each step that
  touches the live site waits for Diesel's word at that moment.

## Put off by Diesel

On 17 November 2026 Diesel said to start building and to settle three points later. Until each
is settled, the build works to the assumption beside it.

1. What an account made for someone who asks to use the platform starts with. Until settled:
   the code's defaults stay off, so a new account gets today's platform, and what it starts
   with is chosen when the account is made. Suggested then: the new parts switched on, while
   the accounts that exist today stay as they are.
2. The shared key. On 17 November 2026 it had $41.39 left of its $200 limit, and the limit
   does not reset. The runs this plan calls for and visitors' lessons (about $10 to $20 for
   a class of 25 in an hour) will not both fit. Until the limit is raised: the balance is
   checked before every paid run and each run is kept as small as its change allows.
3. The day of the talk, which sets the last day for a live change. Until settled: no earlier
   than Monday 23 November 2026, so the last live change is Saturday 21 November.

## Why

Diesel's picture of the platform: the agent is a teaching assistant in a classroom that gets
work delegated to it. Its two key parts are a good personalisation system between the agent
and each student, and keeping the teacher in the loop. (Diesel)

Today the second part is ahead of the first. Every student in a lesson gets the same questions
in the same words. What the tutor remembers about a student changes how much help it gives,
never what it asks. The only personal question is the harder follow-up, which works on the test
copy and is not live. A fixed question cannot stretch a student who is ahead or give a smaller
step to one who is behind. And the teacher is never asked for objectives: the agent writes them
itself, and nothing is judged or reported against them. All progress is counted by step.

The Athens conference is in the week after 17 November 2026. Two items on its list need
building, and this document covers both: a demo of a teacher planning a lesson with open input
and few or no boxes, and examples that differ between students, through one general prompt
that fits every subject and makes use of memory. The other items (the three student personas,
the picture of the system's parts, the privacy wording) are presentation work and not here.

## Goals

1. A teacher plans a lesson by talking, starting from objectives. The agent asks when it has
   too little and never creates a lesson by itself. (Diesel)
2. Every student is judged against the same objectives. The route there fits the student.
   (Diesel)
3. A student with no history gets the lesson as written. (Diesel)
4. The teacher is in the loop three times: before the lesson they see every question the card
   holds, after it they see what each student was really asked, and they hold a switch for
   each part. (Diesel: a tag when a harder question was given, and the options in a Settings
   tab.)
5. Results stay comparable across a class, because everyone answers the same baseline.
   (Diesel)
6. One general prompt that works for any subject. (Diesel)
7. About the same number of questions for everyone, all finishing in the lesson's set time.
   (Diesel)

## What would make this a failure

- A student is marked on a different question from the rest of the class, or on a lowered one.
- A student is shown or told a level, a label, or that their question is the easier one.
- A level or a band is stored about a student. (Diesel: no static levels.)
- A question the tutor wrote, which no teacher saw, counts towards a mark.
- A second model call is used to check a question. (Diesel said no.)
- The teacher can only find out what a student was asked by reading the whole chat.
- A teacher who has an account today and has never opened Settings finds the platform
  behaving differently.
- The agent drafts a whole lesson from a topic alone. (Diesel)
- Prompt text that only fits one subject. (Diesel)

## Constraints

- Built and checked on the test copy first: database `genai4ed_memory`, API on port 8010,
  website on port 3002, with clearly named test accounts (see "The test copy and the live
  site"). Testing never uses the real teachers' accounts or the live database.
- The live site has to carry this work before Athens, for the people who ask to use the
  platform after seeing it. (Diesel) Each step that touches the live site (a migration of
  the live database, a rebuild of a live container, a new account) is done at Diesel's word
  at that moment, with a dump of the database taken first and the running images kept.
- A teacher who has set nothing gets today's platform: the same prompt text, the same reply
  format, the same screens (my call). The teacher's prompt keeps its version as well. The
  tutor's version label may change once, as it did when the harder follow-up was added,
  because that label takes in the words of parts that are switched off (`scaffold.version`).
  A test pins that the text sent for a lesson with every switch off is today's, character
  for character (my call).
- Prompt rules (Diesel): examples and positive instructions work better than lists of "never";
  every rule traces back to a failure seen in a run; every change to the teacher's prompt is
  run against 30 to 50 realistic teacher messages.
- Any change to the teacher's prompt, to a field note of the lesson brief or to the fixed
  "Where this lesson stands" sentences makes a new prompt version and calls for a live run of
  the 50 bench cases, about $1.30 to $1.50. A tutor reply costs about 2 cents and an extra
  question about 4. Every lesson on the site spends from one shared key. Its $200 limit does
  not reset, and on 17 November 2026 it had $41.39 left.
- Words on screen are plain, with no long dashes, ages and not year groups, no decorative
  colour bars, and never a label on a student.
- Backend changes are written test first. About 2,400 lines of tests across nine files pin
  today's memory note, memory settings and harder follow-up; they keep passing or are changed
  on purpose.
- Nothing is committed or pushed without Diesel's word. That includes this document.

## Words

- **Objective**: what students should be able to do by the end, in plain words. On the card
  today as a list of plain strings (`objectives`).
- **Step**: one part of the lesson, in the teacher's order. It holds its questions, its finish
  line and, where there is one definite answer, the answer.
- **Finish line**: what a student has to show to have done a step (`success_criteria`, shown
  to teachers as "Done when").
- **Baseline**: a step's own question or questions, as on the card. Every student answers it
  and it is the only thing that counts.
- **Easier step**: one smaller question that is part of the way to the baseline.
- **Deeper question**: one question that goes further into the same objective: why the method
  works, a comparison, the student's own example, a case where the method fails. Deeper, not
  bigger: never larger numbers and never a later step's content. (Diesel liked "deeper, not
  bigger".)
- **Question ladder**: the three together for one objective, each one a rung. In code both
  words need other names: "ladder" and "rung" already mean the order of help (`LADDER` in
  `backend/app/study.py`, `off_ladder` in `backend/app/enums.py`, `rung_permitted` in the
  turn's manifest).
- **Personal version**: a card question told in a setting this student has talked about, with
  every number and what is asked kept.
- **Extra question**: an easier step or a deeper question. Extras carry no mark.
- **Tag**: a word the teacher sees beside a question a student was asked: `baseline`,
  `personal`, `easier`, `deeper`. Students never see tags.

## Planning a lesson

Today the agent drafts at once when the teacher's words say what students will do. It writes
the objectives, steps, questions, answers and finish lines itself and marks them to check. It
asks only for the length and the age, and for the kind of activity when the words name just a
topic.

With the switch **Ask me questions before drafting** on:

- The agent writes nothing of its own on the card (no objectives, steps, questions or answers)
  until it has three things from the teacher: at least one objective, the students' age and
  the lesson's length. Until then nothing is saved to the card at all, the teacher's own
  words included: they stay in the conversation and go on the card as given when the lesson
  is drafted. A card half filled with no steps would need states of its own (my call).
- An objective is the teacher's when the teacher wrote it or agreed to one the agent offered.
  When the teacher names only a topic or attaches a document, the agent asks what the students
  should be able to do by the end, and may offer two or three example objectives inside that
  question. They go on the card only once the teacher picks or changes them.
- This holds even when the teacher says "you decide": the agent offers objectives and waits
  for a yes. One short exchange keeps the teacher the author of what the lesson is for
  (my call).
- It asks only for what is missing, at most two questions in a message, as today. A teacher
  who gives all three in the first message gets a draft at once.
- With the three in hand it drafts a generic plan that fits the length: steps, a question for
  each, finish lines and answers. It says plainly that these are its own and need checking, as
  it does today. (Diesel: "if the teacher only defines objectives, the AI puts a generic
  lesson plan".)
- What the teacher gives is kept in their words and order, as today. A teacher's own question
  can sit on any rung of the ladder. (Diesel agreed.)
- It does not ask for the kind of activity. It still records its own guess at the kind,
  because the research record is built on it (my call). Whether those labels are still needed
  is a question for the researchers and is not settled here.
- The help rules (hints, a worked step, giving the answer) stay at their defaults unless the
  teacher states their own in words, as today.
- One exception: the button that follows up a shared difficulty keeps drafting at once
  (my call). Pressing it is the teacher's own request for a lesson, and the button expects a
  card back (`follow_up` in `backend/app/routers/thread_lessons.py`), so a question asked
  there would not be seen. The difficulty the teacher picked is the new lesson's objective,
  in the agent's words. The age and the length come from the lesson being followed up where
  the agent is shown it. Whatever the agent filled in, it says is its own to check. The
  variant's prompt states the exception, and one bench case covers it.

The boxes. The activity box and the tutor line with its quick choices sit in the typing area
today. The switch **Show the quick-choice boxes** hides both. Hidden, the teacher describes the
lesson in their own words; the API already takes plain text alone. The blank screen today says
"Write the lesson as you'd teach it: the steps, the questions, and how the agent should
behave." With ask-first on it asks for what the students should be able to do by the end.

The prompt. Ask-first is a variant of the teacher's prompt with its own version. With the
switch off the prompt is today's, byte for byte. Where the server can hold the rule in plain
code it should: today the "Where this lesson stands" block and the send-back check decide
between drafting and asking from the kind of activity and whether the teacher gave every step
or question; with ask-first on they turn on whether an objective, the age and the length were
given.

The test set. The variant needs new bench cases, at least: a topic alone (it asks for
objectives and the card stays empty); a document alone; objectives without the age or the
length; all three given (it drafts and says what is its own); the teacher's own questions kept
word for word; an offered objective that stays off the card until agreed; "you decide"; never
more than two questions in a message. Cases in today's set whose expected result changes under
the variant (the agent drafting at once from a topic or a document) get a second expected
result for it, and today's prompt keeps today's expectations. The follow-up button gets a
case too. Then a live run for each position of the two planning switches that a teacher on
the live site can reach: ask-first alone, the ladder alone, and both (see Order of work).

## The lesson card

- Each step that asks the student for something names the one objective it serves. One, to
  keep the card readable; where a step serves two, the agent names the main one (my call). An
  objective may have several steps. A step that names none, such as a warm up, counts towards
  none.
- The card shows each objective with a line **Met when**, made of the finish lines of its
  steps. There is no new field: what counts as meeting an objective is the finish line of the
  step or steps that serve it, and the teacher changes it as they change any finish line
  (my call). (Diesel: what counts as meeting the objective may be set by the teacher.)
- An objective that no step serves is shown with a plain note saying so. It does not block
  approval (my call).
- With the switch **Write a question ladder for each objective** on, the agent drafts two
  more questions for each objective: an easier step and a deeper question, each with its
  answer where there is one. They sit on the step that holds the objective's main question,
  normally its last step (my call). That step's own question is the baseline. The teacher can
  ask for an extra on any other step.
- Extras are never required. The approval check asks for nothing new, and seeing the ladder on
  the card before approving the lesson is the teacher's check. There is no separate approve
  button for it (my call).
- The teacher changes anything on the card by telling the agent, as today. Typing into the
  card is not in this change.
- A card saved before this change, where no step names an objective, loads and behaves as it
  does today, and its results are shown by step. Every stored card is checked again each time
  it is read, so the old shape must keep loading.
- With both planning switches off, the agent is shown none of the new fields and its prompt
  version is today's. With either on, steps name their objective. The extra questions are
  drafted only with the ladder switch on.

## What the tutor does

**Baseline first.** Every student is asked the step's own question from the card, and only the
answer to it counts towards the step and its objective. A strong student still answers it
first. (Diesel agreed.)

**No history.** The lesson starts as written. The tutor knows nothing to build a setting on
and does not guess. Extras then come only from what the student does in this lesson. (Diesel:
with no history every student gets the original lesson; the agent cannot assume; "mostly
personal history, the current lesson also tells".)

**A question in the student's setting.** Switch: **Use what a student has talked about in
questions and examples**.

- When the tutor knows of something this student cares about, it may tell a card question in
  that setting. Every number stays and so does what is asked, so the card's answer still
  holds. The unit may change with the setting; the number in the answer does not. Example: "A
  taxi costs £3 plus £2 a mile. The fare was £15. How many miles?" becomes "Hiring a motorbike
  costs £3 plus £2 an hour. The bill was £15. How many hours?" The card's answer, 6, still
  checks it.
- It draws only on hobbies and everyday interests the student brought up themselves: in this
  lesson, or in the repeated end of their last lesson where the teacher has that memory option
  on (`recent_lines`). Nothing new is stored about a student (my call; see Privacy).
- A question about the lesson's own material (a passage, a picture, a table of data) is asked
  as written.
- When the tutor knows of nothing, or is unsure, it asks the question as written.

**Examples and explanations.** The tutor may already use its own examples and analogies when
it explains or hints. With the same switch on it is asked to build them on what it knows of
this student: a setting they care about, and a mix-up noted from before. An example is not a
judged question, so it needs no check. (Diesel's motorbikes example.)

**The easier step.** Switch: **Give an easier step after wrong tries**.

- Allowed when all of these hold: the step has an easier step on the card; the student has had
  at least one wrong try at the baseline on this step, and as many as the lesson's rules ask
  for before a worked step (`partial_after_attempts`, one by default); no worked step has
  been given on it; the easier step has not been used on it; the student still has their
  extra question for this objective; there is time (below); and the lesson's rules allow
  hints.
- So it becomes allowed on the same turn as a worked step, and the tutor is told to give the
  easier step first. Nothing in code holds the worked step back, so a tutor that leaves the
  easier step out can still give a worked step (my call). An earlier draft said two wrong
  tries. Under the default rules a worked step is allowed after one, so the easier step
  would almost never have been reached.
- The tutor introduces it as one part of the question, never as an easier one. The student
  gets one try. Right or wrong, the tutor says what the answer shows and goes back to the
  baseline.
- It carries no mark, and a wrong answer to it is not a wrong try on the step, so it never
  brings the worked step or the answer closer (my call).
- The teacher's help rules apply to it as to any question, and its answer is not given before
  the student's try.
- It never counts as meeting anything by itself.
- With no easier step on the card, the tutor helps as it does today. It does not write an
  easier question of its own (my call: Diesel said easier "needs to be careful", and an easier
  question that no teacher saw is the least careful kind).

**The deeper question.** Switch: **Ask the deeper question when a student gets a step right
first time**. This is today's harder follow-up switch (`harder_questions`) with new words.

- Today's rule stays: only after the student got the step right first time with no help; one
  try; no mark; never in a study condition.
- When the step has a deeper question on the card, the tutor asks that one, and may tell it in
  the student's setting like any card question. Its answer on the card is not given before the
  student's one try. After the try the tutor may explain in full, as today.
- When the objective has no deeper question anywhere on the card, the tutor writes its own,
  as the harder follow-up does today, and the teacher's views say the tutor wrote it.
- When the objective has one on another step, the tutor writes none on this step, and the
  student's one extra waits for the card's question (my call: a question the teacher saw
  comes before one the tutor makes up).
- It must also work on the lesson's last step. Today the harder follow-up is off there,
  because its closing words ask the next step's first question. On the last step the tutor
  closes the lesson instead.
- When the student seems tired, hurried or unsure, the tutor leaves it out, as today.

The harder follow-up is the model for both extras: an open question kept on the student's step
row, one answering turn, its own evidence record, no mark, then on with the lesson.

**How many, and the clock.**

- A student gets at most one extra question for each objective, easier or deeper (my call on
  the number, from the page Diesel saw; it becomes a setting later). A step that names no
  objective counts by itself, which is today's rule for the harder follow-up.
- No extra when the student is behind the clock. The builder picks a simple rule from the
  facts a turn already has. A suggested one: an extra is allowed only while the share of the
  lesson's time left is at least the share of steps left. It needs the student's real start
  time: today the minutes are counted from the oldest of the last 30 messages, which reads low
  in a long lesson (read from the code, not tested).
- Order and skipping stay as they are. (Diesel: they do not really matter.)

**Whatever the switches say**, three things never happen (Diesel agreed): the tutor gives an
answer against the teacher's rule; the baseline is lowered or replaced; a student is shown or
told a label, a level, or that a question is easier.

## What the tutor is told

- One general block, kept in one module the way `backend/app/agent/harder.py` keeps the harder
  follow-up: all the words in one place, none of them in the prompt while the switches are
  off, and easy to take out again.
- It fits any subject. It holds no subject's own terms, and any examples in it come from more
  than one subject. (Diesel)
- It says how to use what is known about the student: to choose how much to cue (as today), to
  pick a setting, to build examples, to watch for a mix-up noted before, and to decide whether
  to use an extra that is allowed. With nothing known, it teaches the lesson as written.
- What is allowed on this turn is worked out in plain code and given in the "Right now" lines:
  for example that the easier step may be given, with its words. The code decides whether the
  tutor may; the tutor decides whether it does. An extra's words reach a turn only when that
  extra is allowed for that student on that turn.
- Nothing about one student goes into the cached opening, which is shared by all the students
  of a lesson (the fixed prose, the lesson, the material, the reply format). Everything
  personal comes after it.
- A student for whom all of it is off (the switches, a study condition, a lesson comparing
  teaching approaches) gets a prompt with nothing of it in.
- Lines that stop being true change only when a switch is on, for example "the student sees
  the step's own question above the box".
- The words follow Diesel's prompt rules: examples and positive instructions, and each rule
  that stays traces to a failure seen in a run.
- The reply. Prefer the fields it already has: `task` already carries the question on the
  table and is covered by the leak check, and the moves `simplify` and `harder` already exist.
  One new field is needed: the tutor's mark that it retold a card question (see The checks).
  It is included only for lessons where that switch is on, so every other lesson keeps
  today's reply format and prompt text.
- Done, before Athens, means a scripted run on the test copy shows it (my call): at least 12
  student conversations with the real tutor, in two subjects, one with numbers and one
  without, with students who have history and students who have none, and every student
  switch on. They are read against a written list.
  - Must be seen: a student with nothing known gets every question in the card's words; a
    student who brought up an interest gets a card question in that setting with every
    number kept, marked, and shown on the teacher's card with its tag; an example built on
    what is known of a student; the card's deeper question after a step got right first
    time; the easier step before a worked step, then back to the baseline.
  - Must never be seen: a changed number or a changed thing asked; a setting the student
    never brought up; a label, a level or the word "easier" said to a student; an answer
    given against the teacher's rule; an extra counted in a mark; a second extra for one
    objective.
  - A run costs very roughly $3 to $8.
- Today's tutor bench cannot show any of this. It is one lesson with six pupils made for the
  run, none with an earlier lesson, and it is fixed to the live API's port. A tutor bench
  with history comes after Athens.
- Mixed positions of the three student switches are covered by tests of what goes into the
  prompt, not by a live run.

## What a student sees

- Above the box: the question in the words the tutor used for this student, where the tutor
  told a personal version, and the extra question while one is open (as the harder follow-up
  does today). Today that line is always the card's first question for the step.
- No tags, no labels, no levels. The deeper question is "an extra". The easier step is one
  part of the question.
- Nothing else on the student's screen changes.

## The checks

- No model checks a question. (Diesel) The checks are plain code, in the supervisor that
  already checks every tutor reply.
- New: when the tutor tells a card question in a student's setting, the numbers in its version
  must be the numbers of that card question, no more and no fewer. For a step with several
  questions, the numbers of one of them. A number written as a word counts as that number. A
  miss is handled like the other checks: one redraft with the reason, asking for the card's
  own wording. If the second draft also misses, the student gets the fixed holding line, the
  teacher gets an alert, and the question is asked as written for the rest of that step
  (my call).
- The server has to know that a question was retold, and only the tutor can say so: it marks
  a retelling in its reply (my call). Comparing the on-screen question (`task`) with the
  card's words does not work. The tutor is already told to "ask a smaller question about
  that part", and `task` is "the question your message actually asked", so the two differ on
  ordinary turns. A marked retelling is checked, shown above the student's box and recorded
  as personal.
- A retelling the tutor does not mark is not checked and not recorded, and the card's own
  question stays above the box. That is a limit to state.
- A question with no numbers cannot be checked this way. That is a limit to state. What is
  left is the rule that questions about the material are asked as written, and the teacher
  seeing the words that were asked.
- The answer guard. Today the leak check matches a card answer as text. A retold question can
  change the unit ("6 miles" becomes "6 hours"), so while a personal version is open the guard
  also has to cover the number in the card's answer. The builder reads how `answer_leakage`
  matches before deciding how.
- The answers of the card's easier step and deeper question are guarded while their question
  is open. A long answer in sentences rarely matches as text; that limit exists today.
- While the tutor's own harder question is open, today's `beyond` flag turns off four of the
  five checks, because the card has no answer for it. Which checks apply while a card extra is
  open is the builder's to settle. Two points are fixed: the extra's answer is not given
  before the student's try, and after the one try at a deeper question the tutor may explain
  in full.
- Nothing checks that the tutor judged an answer correctly. That is true today and stays true
  (see Limits).

## The record

- For each question a student was asked, the record keeps: the step, which rung it was
  (baseline, easier, deeper), whether it was a personal version, whether the card or the tutor
  wrote it, the words asked, the judgment and the student's quoted words.
- New keys on an evidence record need no migration. A new kind of evidence does: the database
  check is rebuilt, as migration `f2a3b4c5d6e7` did for the harder question. The builder
  chooses.
- Extras never touch a mark. The step row's judgment, tries and help counts are about the
  baseline only, as the harder follow-up is kept apart today.
- An objective's result for a student is worked out from the baseline: met when every step
  that serves it is met, otherwise "n of m steps". A step is met as today, when the tutor
  judged the answer met and moved the student on. The view also says how it was met: right
  first time, after n tries, after the easier step, after a worked step, all from marks the
  step row already holds. (Diesel: met the objective, and whether they got it right.) No level
  and no band is stored, and no new table is needed unless the builder finds one is.
- Memory for the next lesson. The counted lines keep counting baseline answers only, so "right
  first time" means the same for everyone. The next tutor is also told, in plain sentences
  with counts, how often the student needed the easier step and how their deeper questions
  went. Never a level. Lines inside the existing note categories need no migration; a new
  category would, because the categories feed database checks.
- The words asked are kept with the evidence, so the teacher can still read them after the
  chat is cleared (the purge command, when it is run, clears chat older than 7 days and keeps
  evidence for 365). The text-free research export must blank them. Today it blanks only the
  quote, the note and the misconception, so the harder question's words already slip through;
  that is fixed here too.
- The positions of the switches are kept with the record, so a result can be read against how
  the platform was set (my call). Each tutor turn already keeps the memory settings it was
  made under (`memory_settings` in the turn's manifest, `backend/app/agent/context.py`); the
  new student switches go the same way.

## The teacher's views

- **Lesson card**: the objectives with "Met when"; on each step the objective it serves; the
  easier step and the deeper question with their answers under the step that holds them,
  marked as never shown to students, as answers are today.
- **One student's card**: a line for each objective (met, or n of m steps, and how). For each
  question asked: the tag, the words asked where they differ from the card, the judgment. A
  deeper question the tutor wrote itself says so.
- **The class**: met or not yet for each objective for each student, with the tags. The view
  by step stays.
- **The end-of-lesson review** is told the tags and the questions asked. Today it sees only
  step judgments and short quotes. Its summary mentions an extra question where one was
  given. (Diesel: a tag or comment in the summary.) That is a new version of the review
  prompt.
- **Research**: the lesson table and the export carry the tags.
- Sentences that promise fixed questions change when a switch is on: "The agent will teach it
  exactly as it stands." and "the same steps, questions, marks and files".
- Nothing new interrupts the teacher. A tag is not an alert.

## The Settings tab

- A new button on the teacher's rail, **Settings**, at `/teacher/settings`. It holds a
  teacher's standing choices. A lesson's own rules stay with the lesson. (Diesel: a Settings
  tab like the Research tab, holding all the recent options as on and off switches.)
- Before Athens it has three panels:
  - **Planning a lesson**: Ask me questions before drafting. Write a question ladder for each
    objective. Show the quick-choice boxes.
  - **Questions for each student**: Use what a student has talked about in questions and
    examples. Ask the deeper question when a student gets a step right first time. Give an
    easier step after wrong tries.
  - **Memory between lessons**: the existing panel with its delete button, moved from the
    Research page. The Research page's line "The memory settings are the only thing here that
    changes anything." goes with it.
- Each row is a title and one grey line saying what on and off do, in the house look: a panel
  with tick-box rows, as the memory panel has.
- Defaults: a teacher who has set nothing gets today's platform. The boxes are shown, the
  agent drafts at once, every question is asked as written, memory is as it is. That covers
  every account that exists today. What an account made from now on starts with is one of
  the points Diesel put off (see "Put off by Diesel").
- There is no master switch. The sketch Diesel saw had one, "Give each student their own
  questions". With the three switches under it all off, every student gets the questions as
  written, so a fourth would only repeat them (my call).
- One row of settings for each teacher, holding for all their lessons. Nothing per class and
  nothing per lesson (my call, as told to Diesel). Today's `memory_settings` table already
  holds the harder switch; widening it or adding a table is the builder's choice.
- A lesson follows the settings of the teacher who owns it, and the student switches are read
  on every turn, as the memory settings are today (`memory_settings.of(db, contract.teacher_id)`
  in `context.py`). So a change takes effect on a student's next message.
- The word is taken three times today: the panel under the typing box titled "Tutor settings"
  with its link "all settings", the "Memory settings", and a read-only box on the Research
  page whose component is named `Settings`. The tab is **Settings**; the panel under the
  typing box gets a title that says it is this lesson's (the builder proposes the words); the
  Research component is renamed in code (my call).
- The rail was written for four buttons. A fifth needs its wrap checked at phone width.

## Study and research

- A student in a study condition gets every question as written: no personal version and no
  extras. Today that holds for the harder follow-up only.
- A lesson made to compare teaching approaches (direct instruction against guided inquiry; the
  lesson's `approach` is set) promises the same steps, questions and answers in both versions.
  It gets every question as written too. Today the harder follow-up is not kept out of these
  lessons; this closes that gap.
- When a study condition or the teacher's memory switch turns memory off, the tutor has only
  this lesson to go on.

## Privacy

- Nothing new is stored about a student except the route record above: the tags and the words
  asked. A personal version's words can name what a student likes ("motorbike hire"), so they
  are treated as the student's own words are: shown to their teacher, blanked in the text-free
  export.
- Remembering what a student likes from one lesson to the next is not in this change. (Diesel
  agreed: later, behind its own switch, after checking the ethics approval.) Today's rules
  work against it on purpose: the review prompt bans the student's own words and personal
  details, and the server drops written lines that copy the student. Lifting that is a
  decision more than a code change, and it needs a delete for one student, which does not
  exist today.
- What goes to the model does not change in kind: the student's words, the memory lines, the
  teacher's lesson and the material. The tutor's call carries no name and no id.

## The test copy and the live site

- The live site is what `docker-compose.yml` brings up: the database `genai4ed` in
  `genai4ed-db` on 127.0.0.1:5433, the API on port 8000 (`genai4ed-api`), the website on
  port 3000 (`genai4ed-web`) and a daily dump into `./backups` (`genai4ed-backup`). People
  reach it through a Cloudflare tunnel on the same machine. While that machine is off,
  asleep or offline, the site is down for everyone.
- The API container runs `alembic upgrade head` each time it starts
  (`backend/docker-entrypoint.sh`). So rebuilding the live API migrates the live database,
  and the dump comes before the rebuild.
- A backend command left on its default settings works on the live database. Every command
  in the plan names its database.
- The test copy is a second database, `genai4ed_memory`, in the same Postgres container. It
  is started by hand and no file in the repo holds the commands. The database user and
  password come from the environment and are never written into a document.
  - The API, from `backend/`: `DATABASE_URL` pointing at `genai4ed_memory`,
    `COOKIE_SECURE=false`, `DEMO_SIGN_IN=true`, then
    `uv run uvicorn app.main:app --host 127.0.0.1 --port 8010`.
  - Migrations: `uv run alembic upgrade head` with the same `DATABASE_URL`.
  - The website, from `frontend/`: `API_INTERNAL_URL=http://127.0.0.1:8010 npm run build`
    (the address is fixed into the build). Copy `.next/standalone` to a scratch folder with
    `.next/static` inside it, and run `PORT=3002 HOSTNAME=127.0.0.1 node server.js` there.
    Afterwards build once more without `API_INTERNAL_URL`, so `.next` does not point at
    port 8010.
- Ports 3000 and 8000 are the live site's and are never used for testing.
- The teacher's bench (`backend/bench/teacher_run.py`) runs in one process against a database
  it makes itself, and refuses any database whose name lacks "eval". The tutor's bench
  (`backend/bench/run_bench.py`) is fixed to the live API's address and is not run as it
  stands.
- There is no sign-up page. A teacher's account is made from the command line
  (`python -m app.accounts teacher --email ...`), which shows the password once. It makes
  the account only: no settings row and no sample lesson. It works on the live database,
  so it is run on purpose and at Diesel's word.

## Order of work

Each stage ends in something that can be shown. Each is built and checked on the test copy,
then put on the live site at Diesel's word.

Before Athens:

1. The work that is built and waiting goes live first: the memory settings, the harder
   follow-up, the picture fold, the parts strip and the Next.js update.
2. The Settings tab with its three panels, and the boxes behind their switch.
3. Planning by talking: the ask-first variant and its bench cases.
4. The card: steps name their objective, "Met when", the ladder drafted and shown. Stages 3
   and 4 both change what the agent is told. Their bench runs come after both are built, one
   for each position a teacher on the live site can reach: ask-first alone, the ladder
   alone, and both. That is three runs, about $1.50 each when clean.
5. The tutor: the general block; a question in the student's setting with the tutor's mark,
   the number check and the student's screen; examples built on the student; the deeper
   question from the card; then the easier step; then the scripted run (see What the tutor
   is told).
6. The record and the teacher's views: tags and the words asked on the student's card, the
   line for each objective, the review told the tags, blanking in the text-free export; then
   the class view by objective and the Research tags.
7. The demo set-up.
   - It runs on the live site, with a clearly named demo teacher and class made at Diesel's
     word, and is rehearsed on the test copy first (my call).
   - Three demo students get history: their earlier lessons are run by script with the real
     tutor. One more has none, to show the card's own words.
   - A setting taken from memory needs three things to be true. The demo teacher has "Repeat
     the end of the last lesson" above 0 (`recent_lines`). The new lesson is in the same
     subject as that student's last one. And that last lesson ended on the interest. The
     memory notes cannot carry an interest (see Privacy).
   - So either an earlier lesson is run so that it ends that way, or the student brings the
     interest up in the demo lesson itself.
   - One new lesson is planned by talking, rehearsed, and a run is recorded to fall back on.

If time runs short, cut from this list in this order: the class view by objective, the
Research tags, the review's mention, the easier step.

Going live:

- What is shown at Athens is what is live. A part that is not built and checked in time is
  left out of both (my call).
- It goes live in three steps (my call): stage 1 by itself; then stages 2 to 4; then stages
  5 and 6.
- Each live step, in order: Diesel's word; a dump of the live database into `./backups`; the
  running images tagged so they can be brought back; the API rebuilt, which brings the live
  database up from `d0e1f2a3b4c5`; the website rebuilt; a check on the live site with a
  clearly named test account.
- Rolling back is the tagged images and, where a migration has to be undone, the dump.
- A switch can be reached on the live site only once the prompt it turns on has had its run.
  Until then it is not shown.
- The last live change is at least a full day before the talk (my call).
- Accounts for people who ask are made from the command line, at Diesel's word.

After Athens: a tutor bench with history; standing tutor rules in Settings (the quick choices
become a teacher's defaults); the number of extras as a setting; a question from the last
lesson; remembering what a student likes, after the ethics check and with a delete for one
student.

## Not in this change

- A way to show the backend and the prompts in the presentation. (Diesel: later.)
- Numbers or content that differ between students. Diesel said they may change; this change
  keeps them fixed, because nothing could check a new answer without a second model (my call).
  It can come later with a plain-code answer check for question types that allow one.
- Remembered interests, and a delete for one student.
- Standing tutor rules, and typing into the card.
- A question from the last lesson; find the mistake; the student choosing the deeper one;
  steering towards a success rate.
- A plain-code flag when the tutor says met and the card's answer is not in the student's
  words.
- Bloom's taxonomy, which waits for the next redesign.
- Removing the activity labels.
- The outcomes card and marks by criterion, which stay as they are.
- A sign-up page. Accounts for people who ask are made from the command line.
- A spending limit for each teacher. Every lesson spends from the one shared key.

## Limits to say out loud

- A model can write a faulty question. In one 2024 study GPT-4 Turbo's maths word problems met
  every criterion 78.8% of the time, so about 1 in 5 failed at least one (Christ, Kropko and
  Hartvigsen, MATHWELL). The safeguards: the teacher sees every card question before the
  lesson, the tutor changes only the setting, and the number check.
- A model can call a wrong answer right. In Khan Academy's 2024 test the best model judged a
  wrong answer correctly 68.5% of the time (Miller and DiCerbo). So only the baseline counts,
  it is judged against the card's finish line and answer, and the teacher sees the words asked
  beside the student's own.
- A retold question with no numbers in it is not checked by anything.
- A retelling the tutor does not mark is not checked or recorded.
- The tutor's part reaches real classes on the strength of a scripted run of about a dozen
  conversations, not a classroom trial. Mixed positions of the three student switches are
  tested in code, not in a live run.
- The live site runs on one machine and one shared key. It is down while that machine is off,
  and when the key's limit is reached the model calls fail for every lesson.
- The ladder is more for the teacher to read: three short questions for an objective where
  there was one.
- "Met" means met in this lesson. One right answer is thin proof, and later lessons add to it.
- Part of this is new. In established products such as ALEKS a question is a family of
  versions built by people to be equally hard. A ladder the teacher has seen, with only the
  setting changing, is close to that. A tutor choosing each student's route from its own
  memory is not: no classroom study of it was found, so it is presented as new.

## Calls made in writing this up

For Diesel to check. Each is marked (my call) where it appears above.

1. "Seem like a good thing" was read as yes to the four suggested answers: a strong student
   answers the baseline first; a teacher's own question can be any rung; interests come later
   behind their own switch after the ethics check; the tutor never gives the answer against
   the rule, lowers the baseline or shows a label.
2. An untouched teacher gets today's platform: the same prompt text, reply format and
   screens. That means variants of the teacher's prompt, each with its own version and bench
   run, while today's keeps its version. The tutor's version label changes once when this
   goes live. The cheaper way is one new prompt for everyone, which changes the agent for
   teachers who touched nothing.
3. Switches hold per teacher for all their lessons. No master switch.
4. One objective for each step. One ladder for each objective, on its last step. No new "met
   when" field: the finish lines are it. An objective with no step is a note, not a block. No
   separate approve button for the ladder.
5. Even on "you decide", the agent offers objectives and waits for a yes.
6. The agent keeps recording its guess at the kind of activity.
7. A question's setting draws only on this lesson and the repeated end of the last one.
   Nothing new is stored about a student.
8. Numbers stay fixed, which is narrower than Diesel's "numbers and content may change".
9. The easier step: allowed from the point where a worked step would be (after one wrong try
   under the default rules) and given first, one try, no mark, not a wrong try, not where
   the rules allow no hints, and never written by the tutor.
10. One extra question for each objective, easier or deeper.
11. A missed number check gets one redraft, then the holding line and an alert.
12. The switch positions are kept with each lesson's record.
13. Names: the tab is Settings; the panel under the typing box is retitled.
14. A student's records stay in Postgres. No vector database and no agent-memory product (as
    answered earlier on 17 November).
15. The tutor marks a retold question itself. One it does not mark is not checked or
    recorded.
16. A deeper question anywhere on the card under an objective comes before one the tutor
    writes.
17. The button that follows up a shared difficulty keeps drafting at once, even with
    ask-first on.
18. The tutor's part is done for Athens when a scripted run of at least 12 conversations
    shows the written list. A tutor bench with history comes after Athens.
19. Going live happens in three steps. Each follows a check on the test copy and a run for
    whatever a live teacher can then switch on, with a dump and the old images kept each
    time. The last change is a full day before the talk.
20. What is shown at Athens is what is live, and the demo runs on the live site with a
    clearly named demo teacher and class.

## Left to the builder

- Data shapes and code names. Not "ladder" or "rung", which are taken.
- How a step names its objective (by position or by an id), given that old cards must load.
- How the agent is shown the new card fields only when a planning switch is on.
- Whether the easier step is a new kind of evidence or keys on an existing one; whether the
  settings widen `memory_settings` or get their own table; where the settings API lives (it is
  under `/api/research/memory` today).
- The prompt words, inside the rules above.
- The rule for being behind the clock, and how the number check reads numbers.
- Which existing checks apply while a card extra is open.
- The screens' layout inside the house look, and the words of the changed sentences.

## Where things are today

Paths are in the repo. Line numbers come from code maps made on 17 November 2026 and will
drift; treat them as starting points.

- State of the tree: branch `backup/2026-11-01`, HEAD `f5060fb`, with uncommitted work that
  this design builds on (the memory settings, the harder follow-up, memory as rows). The test
  copy's database is at Alembic head `f2a3b4c5d6e7`; the live one is at `d0e1f2a3b4c5`.
- Planning: `backend/app/agent/teacher_prompt.py` (the modules);
  `backend/app/agent/thread.py` ("Where this lesson stands" 227-235 and 262-292, the send-back
  check 471-480, the prompt version 295-316); `backend/app/agent/brief.py` (`Step` 91-166, the
  lesson's fields 236-279, `missing()` 451-472); `backend/bench/` (`teacher_cases.py`,
  `teacher_set.py`, `teacher_run.py`, `RESULTS.md`).
- The typing area: `frontend/app/teacher/page.tsx` 425-483 and 653-668;
  `frontend/components/activity-box.tsx`; `frontend/components/quick-choices.tsx`; the rules
  parser `backend/app/agent/policy.py` 341-363.
- The card: `backend/app/agent/cards.py` 162-197; `frontend/lib/api.ts` 336-408;
  `frontend/components/cards/lesson.tsx`; the approve, preview and copy sentences in
  `backend/app/routers/thread_lessons.py` 124, 165-168, 207, 488.
- The tutor's turn: `backend/app/agent/student_mode.py` (kinds of turn 309-320, the model call
  365-373, the supervisor's review 401-426, the harder question 557-588 and 725-746, applying
  a turn 649-834); `backend/app/agent/scaffold.py` (fixed prose 48-83, the step block 299-340,
  help 347-407, time 465-522, memory 525-548, the cached opening 605-617);
  `backend/app/agent/context.py` (memory 323-362, harder 368-383, time 534-563, the data block
  566-597); `backend/app/agent/tutor_reply.py` 62-127; `backend/app/agent/harder.py`;
  `backend/app/agent/policy.py` 91-101; `backend/app/agent/supervisor.py` (`said_by_student`
  61, `review` 171-267, the leak check 214-224); `backend/app/agent/llm.py` 420-469.
- The student's screen: `backend/app/routers/learn.py` 70-77 and 241-261;
  `frontend/app/student/[sessionId]/page.tsx` 313-322.
- The record: `backend/app/agent/steps.py` 17-22; the evidence payload in `student_mode.py`
  693-708; evidence kinds `backend/app/enums.py` 25-34 and their check `backend/app/models.py`
  213; migration `backend/alembic/versions/f2a3b4c5d6e7_harder_questions.py`.
- The teacher's views: `backend/app/agent/classroom.py` (class board 131-282, review 290-351
  and 558-650, student card 361-397); `frontend/components/cards/student.tsx` 177-192 and
  233-250; `frontend/components/cards/class-board.tsx` 179-221;
  `backend/app/research_view.py` 512-563; `frontend/components/research-view.tsx`; the export
  in `backend/app/research.py` 137-146.
- Memory: `backend/app/agent/learner.py` 376-603; `backend/app/agent/memory.py` 79-242; note
  categories `backend/app/enums.py` 247-260.
- Settings: `backend/app/models.py` 526-555; `backend/app/agent/memory_settings.py`;
  `backend/app/routers/research.py` 101-143; `frontend/components/memory-settings.tsx`;
  `frontend/lib/api.ts` 876-889 and 964-977; the rail `frontend/components/app-header.tsx`
  13-35 and 160-210; `frontend/app/research/page.tsx` 99 and 107.
- Study: `backend/app/study.py` 40-90; `backend/app/agent/approaches.py`;
  `backend/app/routers/thread_lessons.py` 441-494.
- The follow-up button: `backend/app/routers/thread_lessons.py` 77-99; `STANDS_FOLLOW_UP` in
  `backend/app/agent/thread.py` 263-266, and its pass through the send-back check at 478.
- The help rules: `backend/app/agent/policy.py` 41-56 (the fields) and 93-99 (the decision).
- The end of the last lesson: `memory.last_said` in `backend/app/agent/memory.py` 146.
- The tutor's version: `backend/app/agent/scaffold.py` 199-223.
- Accounts and sign-in: `backend/app/accounts.py`; `backend/app/routers/account.py`. The
  sample lesson belongs to the demo sign-in (`backend/app/demo.py`).
- The live stack: `docker-compose.yml`; `backend/docker-entrypoint.sh`. The live website is
  on Next.js 16.4.1 and the tree is on 16.4.6. The live prompts are student-v19, teacher-v26
  and review-v7.
