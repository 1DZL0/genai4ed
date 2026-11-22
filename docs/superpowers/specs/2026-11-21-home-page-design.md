# Home page redesign

Date: 21 November 2026. Approved by Diesel from the mockup
`~/Downloads/PACT_Home_Design_v2.html` ("sure do it").

## Why

The home page is the front door for three kinds of visitor: teachers, students, and people who
want to know what PACT is (the Athens audience). Today it leads with a drawing that has to be
decoded before anyone finds their door, and it explains little. Diesel asked for it to be tidier,
better explained, and to show the new PACT logo more.

## Goals

- Each visitor finds their door and reads what it does for them, in their own words.
- The logo is the first thing seen.
- Visitors can read how PACT works and why it is safe.
- The Cyprus Institute is named.

## Non-goals and anti-goals

- No tabs on the home page: the signed-in app already has its own tabs.
- No researcher names on the page: students in a school will see it. Names go on the slides.
- No product screenshots ("See it" was tried in the mockup and dropped).
- No quotes or usage numbers: there are no real users yet, so they would be invented.
- Nothing on the page may claim something PACT does not do today.

## Approaches considered

- A. Doors first, each card explaining its own side, "How it works" further down. Picked.
- B. Two halves, one per role, no shared drawing. Loses the one-agent-between idea.
- C. Today's order with captions added. Still picture-first.

## The design (top to bottom)

1. Top bar: the purple "P." icon and "PACT." on the left; "How it works" (jumps down), "Teacher
   sign in" and a dark "Join a lesson" button on the right. When someone is signed in, the bar
   says who and offers "Sign out of everything"; otherwise that link is hidden.
2. Hero: "PACT." very large, then "Personal Agent for Class Teaching" with P, A, C and T in
   darker type, then the headline "A personal tutor for every student, with the teacher in
   charge." and one explaining line.
3. Two cards. Teacher (purple): four lines and "Sign in as a teacher". Student (green): four
   lines and "Join with a code". A signed-in person's card says "Carry on as ..." with "Not ...?
   Sign in as another ..." under it.
4. Demo line: "Just looking? Try PACT as a demo teacher", shown only while the server's demo
   sign-in is on. Demo sign-in is switched off after Athens, which removes the line.
5. How it works: the existing drawing, then Before, During, After, each with a purple tag for
   the teacher's decision.
6. Safe by design: no real names, every reply checked, the teacher approves, our own database.
7. Dark band: the logo in white, what the full stop means, "A research project of The Cyprus
   Institute" (text; the official logo can be added later).
The old "Internal prototype" note at the bottom was removed at Diesel's request (21 Nov).

## Builder's calls

- While demo sign-in is on, the student card says "Pick your teacher's class to join" and its
  button says "Join a lesson", because the demo student sign-in has no code.
- The signed-in top bar keeps today's simple "Signed in as ..." text and sign-out link rather
  than adding a new account menu.
- The small rule under the full name in the mockup is left out (no decorative bars).
- Checked with a Playwright script against the local preview: the frontend has no test runner.
