# GenAI4ED design system

## Product
GenAI4ED gives every student in a class their own AI tutor, while the teacher stays in charge.
The teacher writes a lesson plan (questions, correct answers, hint wording) and sets how much help
the tutor may give. During the lesson the tutor gives one small step of help per wrong answer and
never goes past the teacher's limit. The teacher's screen stays quiet until a student needs them.

- Users: secondary-school teachers, and students aged 12-16. Any subject (maths, science, English,
  history, geography, languages, arts).
- Used on school laptops and classroom projectors. Must be readable at a glance from across a room.
- Internal research prototype; all names are pseudonyms such as "alex", "10B-03".

## Key screens
Teacher: home (today's lessons), live lesson (whiteboard header, hands up, seating plan of desks),
student's desk (their answers and the tutor's hints, write a note, flag a concern), lesson-over review,
lesson plans list, write a lesson plan (4 steps), classes (register, printable sign-in cards).
Student: my lessons, the lesson (whiteboard header + exercise book page + raise my hand).

## Feel: a real secondary-school classroom
Not a children's app and not a generic SaaS dashboard. Borrow the objects of a classroom, each carrying
real information:
- **Whiteboard** at the top of every lesson screen: lesson title, the questions, the clock. A clean
  white board with a thin grey frame and a marker tray line, handwriting-free.
- **Seating plan**: the teacher sees students as desks arranged in rows facing "front of the class".
- **Raised hand**: how a student asks for help; the teacher's "Hands up" list.
- **Exercise book**: the student's ruled page with a thin margin line.
- **Printed sign-in cards** with cut lines.
Calm, orderly, confident. Mature enough for 16-year-olds, friendly enough for 12-year-olds.

## Colour (use ONLY these)
- Paper #F5F7FA page background; Sheet #FFFFFF cards, whiteboard, desks; Sunken #EEF2F6
- Rule #D9E1EA hairlines and ruled lines; Rule strong #B9C4D1 input/button borders
- Ink #1F2A44 text, primary buttons; Pencil #5C6577 secondary text; Faint #7D8697
- Red pen #C63A2B (wash #FBECEB): ONLY for a student who needs the teacher (raised hand, stuck)
- Tick green #2F6F4F (wash #E8F2EC): correct answers, finished
- Amber #9A5D0C (wash #FBF1E2): paused ("pens down"), drafts, warnings
- Subject colour appears only as a small dot beside the written subject name:
  maths #2B5DAA, science #2F855A, English #7B4397, history #B4632A, geography #19817F,
  languages #B83A6E, arts #C28A12

## Type (use ONLY these)
- Literata (serif): page titles, lesson titles, whiteboard text, question prompts
- Atkinson Hyperlegible Next: everything else (designed for legibility)
- Scale: 13, 15, 16, 20, 25, 31, 39px. Sentence case everywhere. Tabular figures for times/counts.
- 24-hour times (09:37).

## Shape and spacing
- Radius 6px on controls, 12px on sheets, desks and cards. 1px borders. Almost no shadow.
- Generous whitespace; 8px spacing grid; left-aligned text.

## Hard rules (the client rejected these as looking AI-generated)
- NO coloured vertical bars, spines, tabs or thick left borders on cards, notices or headers.
- NO gradients, glassmorphism, neon, purple/pink accents, emoji-heavy decoration.
- NO all-caps eyebrow labels, no "A · B · C" middle-dot meta strings, no arrows appended to buttons.
- NO chalkboard green backgrounds, chalk fonts or cartoon mascots.
- Colour never carries meaning alone; always pair with a word or icon.

## Components
- Buttons: primary = ink fill, white text; quiet = white with rule-strong border; plain = underlined text.
- Help-ladder gauge (teacher side only): 5-6 small rising bars, filled ink up to the level reached.
- Tick mark in tick green for a right answer; a small cross in pencil for "not yet".
- Raised-hand icon (simple line hand) in red pen for students waiting.

## Motion
Only in response to actions (panel slides in, tick draws itself on a right answer). Respect reduced motion.
