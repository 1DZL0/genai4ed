# GenAI4ED demo video: storyboard

## Second pass for the research meeting (30 October 2026)

Two notes on the 26 October cut: the scrolls were not smooth, and the student and the tutor
read as two machines talking past each other. The transcript showed why: the tutor opened by
asking what per cent means and the scripted student answered a different question four times
("10% of 60 is 50", "is it 54?", "600?"). Same structure as before (both screens for a few
seconds, then the student alone, then the teacher's view), two changes underneath.

- **The student is written live, not scripted.** The teacher's first step is now a quick
  question (10% of 60, and how), so the opening exchange is about one concrete thing. The
  student's messages are written turn by turn by a model playing a 13-year-old who texts like
  one, from a beat plan and the tutor's actual message (`backend/bench/pupil_line.py`, run by
  the recorder for each turn). The arc: a right start, a real slip (30% of 60 is 30, "cos it
  says 30 percent"), one press of "Give me an example", a near miss (6 + 6 = 12?), the teacher's
  note arriving through the tutor, then 6 + 6 + 6 = 18 in their own working. The student
  chapter plays at natural pace (tempo 1.0) so the exchange can be read; the teacher chapters
  run at 1.5. Typing is word by word at an uneven speed, and new turns settle onto the page
  (`said-in`).
- **Scrolls are glides.** At each scroll mark the recorder captures the teacher's card pane
  whole, as one tall image (strip by strip under the sticky heading, the camera paused), and
  the editor glides over it at 30 frames a second, resting at each key. A live scroll filmed
  at about 12 frames a second was a staircase, and blending frames only smeared it.

| # | Scene | Screen | Headlines |
|---|---|---|---|
| 1 | The teacher writes the lesson | teacher | The teacher describes the lesson in their own words. The agent drafts it: steps, questions, what counts as done. The teacher sets the rules: hints yes, the answer never. Every step and every rule, read back on one card (the glide). Nothing reaches a student until the teacher approves it. |
| 2 | The lesson starts | both | One lesson, two screens: the teacher's and a student's. |
| 3 | A student works with the tutor | student | Each student has the tutor to themselves. A first question, answered in their own words. A wrong turn. The tutor asks, it doesn't tell. Stuck? One press. An example, never the answer. Closer now. Still theirs to finish. Three tries in, the teacher is told. Quietly. The teacher's note arrives, through the tutor. And they get there, in their own working. |
| 4 | What the teacher sees | teacher | Meanwhile, the teacher sees the whole class. Struggling students are flagged, with the reason why. One sentence from the teacher, passed on by the agent. When the lesson ends: how the class did, and a note on each student. Nothing reaches a student until the teacher confirms it (the glide). |

Recorded with class 9T Maths (9T-02 on camera, the other three driven by `live_pupils.py`
as before). `record.py` writes `tall/*.png` and a `tall` entry in `timeline.json` beside the
frames; `build.py` renders glide scenes from it (`"glide"` entries in SCENES, keys in seconds
and pixels, `"end"` for as far as the pane goes).

## The cut for the research meeting (26 October 2026)

Feedback on the first cut: two interfaces side by side for the whole video were hard to
follow. The new cut shows both screens together for a few seconds only, then the student's
conversation on its own, then the teacher's screen showing what that conversation produced.
It is styled as a short product film: one framed screen at a time on a dark stage, a chapter
label and a headline above it in the product's own fonts, slow zooms onto the part that
matters, crossfades and short chapter cards. About 90 seconds.

| # | Scene | Screen | Headlines |
|---|---|---|---|
| 0 | Title | card | GenAI4ED. A class agent that teaches inside the teacher's rules |
| 1 | The teacher writes the lesson | teacher | The teacher describes the lesson in their own words. The agent drafts it: steps, questions, what counts as done. The teacher sets the rules: hints yes, the answer never. Every step and every rule, read back on one card. Nothing reaches a student until the teacher approves it. |
| 2 | The lesson starts | both, side by side | One lesson, two screens: the teacher's and a student's. |
| 3 | A student works with the tutor | student | Each student has the tutor to themselves. A wrong answer gets a question back, not the answer. Stuck? One press asks the tutor for help. Still guessing. Three wrong tries, and the teacher is told. A note from the teacher arrives, through the tutor. They work it out, in their own working. |
| 4 | What the teacher sees | teacher | Meanwhile, the teacher sees the whole class. Struggling students are flagged, with the reason why. One sentence from the teacher, passed on by the agent. When the lesson ends: how the class did, and a note on each student. Nothing reaches a student until the teacher confirms it. |
| 5 | Close | card | GenAI4ED. Teacher-governed AI for the classroom. A research project. |

Scene 4 replays minutes the viewer has already seen from the student's side: the alert, the
note the teacher typed, then the summary at the end.

How it is made: `tools/video/record.py` records one live lesson on both screens at laptop size
with a named mark at every moment worth cutting to (class 9N Maths, students 9N-01 to 9N-04,
9N-02 on camera; the other three driven by `backend/bench/live_pupils.py`). Then
`tools/video/build.py` composes the cut from those marks (`--stills` to check the zooms first,
`--tempo` for pace). Output: Downloads/genai4ed-research-meeting.mp4 and a `-no-captions`
version for talking over.

## The first cut (23 October 2026)

For the slot in the literature presentation, after the papers: "so we built this". One take,
split screen where the teacher and a pupil act on each other, captions on screen, no voice
unless we add one later. Everything on screen is the real platform with the real model;
pseudonyms only.

The point the video must land: the teacher writes and runs the lesson, the agent teaches
inside the teacher's rules, and the two sides talk through it. The agent is a useful hand,
not the teacher.

## Cast

| Who | Account | Notes |
|---|---|---|
| Teacher | teacher-demo | class 9P Maths, four pupils |
| Students | 9P-05 to 9P-08 | driven by the bench personas: steady, struggling, answer seeker, anxious |
| On camera | 9P-06, the struggling one | the only student screen shown; the other three show on the board |
| Lesson | Percentages of amounts | written live in shot 2 from the lines below |

## Shots

| # | Time | Screen | What happens | Caption |
|---|---|---|---|---|
| 1 | 0 to 5 s | title | The lesson title over the paper background. | A teacher-governed class agent. The teacher writes the lesson, the agent teaches it, one student at a time. |
| 2 | 5 to 22 s | teacher, full | The teacher types two messages in the thread (T1 and T2 below). The lesson card builds on the right: four steps, then the help pills. Waiting for the agent is sped up. | The teacher writes the lesson in their own words. The agent drafts it; the teacher decides. The subject comes from the teacher: the same for history or English. |
| 3 | 22 to 28 s | teacher, full | The teacher reads the card, presses Approve, chooses 9P Maths, presses Start. | Students see nothing until the teacher approves and starts it. |
| 4 | 28 to 44 s | split: pupil left, teacher right | 9P-06 opens the lesson. The tutor explains per cent and asks the first question. 9P-06 answers wrong ("10% of 60 is 50"), presses "Why is it wrong?", gets a hint, not the answer. The board on the right fills with four pupils as they start. | Each student has the agent to themselves, inside the teacher's rules: a hint, a worked step after one wrong try, never the answer. |
| 5 | 44 to 58 s | split | 9P-06 is marked struggling on the board (amber, with the word). The teacher types T3 in the thread. On the left, 9P-06's screen shows the teacher's words arriving through the tutor, and 9P-06 gets it right. | The teacher sees the whole class and steps in. The agent does what the teacher says. |
| 6 | 58 to 68 s | teacher, full | The class board with four states, then the outcomes card: who finished, who needs going over, the depth each pupil showed, the teacher confirms a note. | Every judgment is recorded, for the teacher and for the research. |
| 7 | 68 to 72 s | title | Close. | GenAI4ED. Built for research, with teachers. |

## The teacher's lines

T1, the lesson:

> Year 9, percentages of amounts, 20 minutes, no calculators. Start by reminding them that per
> cent means out of 100 and that 10%, 50% and 25% are a tenth, a half and a quarter. Then a
> worked example, 30% of 60, by finding 10% and multiplying up. Then four of their own,
> building up to a sale price: a £45 jacket with 20% off. Finish with a challenge: is 30% of 50
> the same as 50% of 30, and why?

T2, the rules:

> Hints any time, but a worked step only after one wrong try, and never give the final answer.
> Tell me straight away if anyone is struggling or upset. Everything else can go in the record.

T3, to a pupil, during the lesson:

> Tell 9P-06 to find 10% of 60 first and write it down, then we only need three of those.

## What the pupils do

The bench personas (steady, anxious, steady) drive 9P-05, 9P-07 and 9P-08 off camera, their
words written by a model from the tutor's actual questions, so the board looks like a class. 9P-06's beats are fixed so shot 4 and 5 happen on cue: a wrong first answer,
the "Why is it wrong?" button, a second wrong try (which raises the struggling alert), then,
after the teacher's message, the right answer.

## Before the take

- Today's work committed and the live site on the same build.
- Underlined links on the class board, outcomes card and lessons list turned into pills.
- One bench run on the current prompt wording.
- A dry run of the whole flow with this script, to time the waits and catch anything odd.
- Fresh accounts: teacher-demo's class 9P Maths with pupils 9P-05 to 9P-08 (9P-01 to 9P-04 are the
  professor's class; these are new, so no earlier conversations show), the previous demo lesson removed from the list.

## How it is recorded

The driver from 22 October (two browser contexts, the browser's own screencast, speed marks
while the model thinks, caption marks) with a new script following the shots above; then the
builder cuts it to the split screen and burns the captions. Output: one MP4 with captions and
one without, in Downloads.
