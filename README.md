# GenAI4ED

One AI class agent between a teacher and their students.

- The **teacher** talks to the agent in one conversation: describe a lesson, change it by saying so, approve it, start it with a class, ask how the class is doing, open a student, end the lesson, confirm the marks.
- Each **student's** lesson is a conversation with the same agent. It runs the activity, judges answers, helps, and notices who is struggling or upset.
- The **server** enforces the teacher's rules on every reply (no answers before the rules allow, no writing the work, no skipped judging), records every turn with what the agent was shown, and builds every card the teacher sees from records, never from the model's word.

> Not for real students until the school, the DPO, ethics approval and consent are settled.

## Run it

Needs Docker Desktop and an OpenRouter key.

```bash
cp .env.example .env            # put your OPENROUTER_API_KEY in it; set OPENROUTER_MODEL
docker compose up -d --build    # database, api, web
```

Open <http://127.0.0.1:3000>. Use `127.0.0.1`, not `localhost`.

Without a key the agent is a scripted stand-in: everything works, the replies are canned.

## Show it

1. <http://127.0.0.1:3000/login> and press **Teacher 1**. A new teacher gets three sample lessons, ready to start.
2. Describe a lesson in the box ("A 30 minute lesson for year 8 on percentages of amounts. Hints are fine, never give the final answer."). Read the card, press **Approve**, choose a class, press **Start**.
3. In another tab, <http://127.0.0.1:3000/join> and press **New student of Teacher 1**. Open the lesson and talk to the agent.
4. Back as the teacher: ask "how is the class doing?", open a student, send the agent a note about them, end the lesson, confirm the outcomes. The student then sees the mark and your comment.

A browser can be a teacher and a student at the same time, in different tabs.

To start again from nothing:

```bash
docker exec genai4ed-api .venv/bin/python -m app.research wipe
```

## The model

`OPENROUTER_MODEL` in `.env` picks it, then `docker compose up -d api` to restart. `anthropic/claude-haiku-4.5` is a good balance; `google/gemini-2.5-flash-lite` is cheap for bulk testing but weaker at judging.

Every teacher message and every student message is one model call, plus one redraft if the first reply broke a rule. Nothing runs in the background. Each call is built from scratch: a student's call holds the lesson, the rules and that student's own conversation, nothing about anyone else, and the ids of everything used are stored with the turn.

## Research

Set `STUDY_ACTIVE=true` in `.env` and the researcher, not the teacher, decides the one thing being compared: each student is assigned memory on or off (flipping each lesson) and every lesson uses the fixed help ladder. Every rule check on the first draft is recorded whether or not it was corrected.

Set `RESEARCH_KEY` and open <http://127.0.0.1:3000/research> for counts per lesson and condition. No names, nothing a student wrote.

```bash
docker exec genai4ed-api .venv/bin/python -m app.research export --out /tmp/export   # CSVs, pseudonyms only; add --with-text for words
docker exec genai4ed-api .venv/bin/python -m app.research judge --out /tmp/export    # a model checks each reply for a leaked answer
docker exec genai4ed-api .venv/bin/python -m app.research purge                     # delete what is past its retention date
```

## Develop

```bash
cd backend && uv sync --extra dev && uv run pytest -q     # needs the db container on 127.0.0.1:5433
cd frontend && npm install && npx tsc --noEmit && npx eslint app components lib
```

After changing code: `docker compose up -d --build api web`.

## Where things are

```text
backend/app/
  agent/context.py     what the agent is shown per conversation (the isolation boundary)
  agent/thread.py      the teacher's turn and every card
  agent/student_mode.py  one student turn: reply, checks, records
  agent/supervisor.py  the checks on every reply to a student
  agent/policy.py      the teacher's rules, compiled and read back
  agent/memory.py      what the records say a student knows
  agent/classroom.py   the class board, a student's record, outcomes
  routers/thread.py    the teacher API: messages and buttons
  routers/learn.py     the student API
  routers/research.py  the researcher's counts
  study.py             conditions and the help ladder
  research.py          summary, export, judge, purge, wipe
frontend/app/
  teacher/             the conversation and the card beside it
  student/             the lesson, and the result afterwards
  research/            the counts page
```
