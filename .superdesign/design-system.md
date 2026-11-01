# GenAI4ED design system

## Product

GenAI4ED is a teacher-governed class agent for secondary schools. A teacher writes a lesson
with the agent in one chat thread; the agent then teaches it to each student one to one, inside
the teacher's rules, while the teacher watches the class board and steps in. A researcher reads
the records afterwards. Three screens: the teacher's thread with one card on the right (lesson,
lessons list, class board, student, outcomes), the student's lesson page (a ruled working sheet
with a chat), and the research view. Users are teachers and pupils aged twelve and up, on school
hardware, often by keyboard.

Jobs the teacher card must do: show what the lesson is at a glance, let the teacher approve it,
start it with a class, teach it again, and see how it went. The agent fills a lesson in as the
teacher talks; the card reads it back.

## The look: a calm classroom

Everything is borrowed from a school room that every subject shares: cool exercise-book paper,
blue-black pen for what matters, pencil for the quiet things, and the teacher's red pen, spent
on one thing only, a student who needs the teacher. Colour never carries meaning alone: every
coloured thing also has a word.

### Colour tokens (CSS variables in app/globals.css, exposed as Tailwind colours)

| Token | Value | Use |
|---|---|---|
| paper | #f5f7fa | page background |
| sheet | #ffffff | cards |
| sunken | #eef2f6 | quiet pills, inset boxes |
| rule | #d9e1ea | borders, dividers |
| rule-strong | #b9c4d1 | button borders |
| ink | #1f2a44 | text, primary buttons |
| ink-hover | #2d3b5c | primary hover |
| pencil | #5c6577 | secondary text, labels |
| faint | #656e7f | tertiary text (still AA on paper) |
| red-pen / red-pen-wash | #c63a2b / #fbeceb | needs you, remove |
| tick / tick-wash | #2f6f4f / #e8f2ec | finished, approved, ready |
| amber / amber-wash | #9a5d0c / #fbf1e2 | struggling, waiting on the teacher, check this |
| progress / progress-wash | #2457a5 / #e8eff9 | a student at work, running now |
| cover-maths #2b5daa, cover-science #2f855a, cover-english #7b4397, cover-humanities #b4632a, cover-geography #19817f, cover-languages #b83a6e, cover-arts #c28a12, cover-other #56607a | | subject colours, as a small dot or word before the title |

Four student states, always beside their word: red needs you, amber struggling, blue working,
green finished. Classes are told apart by a muted colour dot picked from the label.

### Type

- Sans: Atkinson Hyperlegible (`font-sans`), for everything.
- Serif: Literata (`font-serif`), for card titles only (`text-xl font-semibold`).
- Scale from a 16px base: xs 13px, sm 15px, base 16px, lg 20px, xl 25px, 2xl 31px.
- Card body text is `text-sm text-ink`; row labels are `text-xs font-bold text-pencil`;
  captions are `text-xs text-pencil`. Numbers that line up use `.figures` (tabular).

### Shape and space

- Cards (`Sheet`): white, `border border-rule`, radius 12px, padding 20px by 16px.
- Controls: radius 6px. Pills and pill buttons: fully rounded.
- Speech (chat bubbles): radius 20px.
- Rows inside a card: `py-2`, label then content with `mt-1`. Sections divided by
  `border-t border-rule`.
- Buttons: height 40px (sm 32px), `font-semibold`. Variants: primary (ink on white text), quiet
  (white with rule-strong border), red (outline red-pen), plain (underlined pencil text), pill and
  pillDark (rounded).
- Status pill: `rounded-full px-3 py-1 text-sm font-semibold` in a wash with its colour
  (tick-wash for Ready to teach, amber-wash for Draft, sunken for an earlier version).
- Small pills (depth, kind, materials): `rounded-full bg-sunken px-2 py-0.5 text-xs`.
- Focus ring everywhere: 2.5px solid ink, offset 2px.

### Motion

Almost none. Colour transitions on hover (`transition-colors`). No entrance animation, no
parallax, nothing that moves on its own in a classroom.

## House rules (hard constraints)

- No em dashes or en dashes anywhere in UI text; use commas, colons or full stops.
- No gradients, no coloured vertical bars, no all-caps text, no decorative icons.
- Plain words a teacher would say. Buttons say what they do ("Start it with 9P Maths").
- Colour never carries meaning alone; every coloured pill or dot has a word next to it.
- Contrast at least 4.5:1 for all text. Keyboard first.
- Use ONLY the fonts, colours, spacing and component styles above. Do not introduce any fonts,
  colours or visual styles not in this file.
