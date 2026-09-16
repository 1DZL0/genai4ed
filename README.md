# GenAI4ED — a teacher-governed class agent

Internal prototype for the GenAI4ED pilot

The platform is built around one **class agent** that sits between the teacher and every student:

```text
teacher ──describes the lesson, materials, rules──▶ class agent (design)
                                                          │ approved lesson brief
                                                          ▼
student ◀──────── conversation: asks, judges, helps ──▶ class agent (student)
                                                          │ judgments, signals, evidence
                                                          ▼
teacher ◀── who needs you, patterns, answers, outcomes ── class agent (classroom)
```

The teacher never fills in a lesson form: they tell the agent what they want and attach material, and
the agent keeps a lesson brief up to date beside the conversation until the teacher approves it. Each
student's lesson *is* a conversation with the agent, which runs the activity, judges answers against
the brief and decides what to do next. The teacher sees meaningful signals rather than chat logs, can
ask the agent about the class, and can guide one student's agent.

It is literally one agent, so **what it is shown in each conversation is decided in one place**
(`backend/app/agent/context.py`): a student's context is the brief, the teacher's rules and that
student's own record, and every turn stores a manifest of exactly what was used.

> **Not for student use.** School/DPO review, ethics approval, age-appropriate information, and parental
> authorisation or student assent must all be settled first (concept note §4, §7). Nothing here should be
> pointed at a real class until that concludes.

## Design commitments

These are load-bearing. Changing one is a design decision, not a refactor.

| Commitment | Why |
| --- | --- |
| The teacher's rules are **enforced server-side, after generation** | TASD: "no direct answers" prompting reduced but did not eliminate answer leakage. Rules said in words are compiled (`agent/policy.py`); every reply to a student is checked (`agent/supervisor.py`) and regenerated or withheld |
| **Context is assembled per conversation** and recorded | One agent serves everyone, so isolation is a property of what it is shown, and each turn's manifest makes that auditable |
| The agent's **judgments are evidence, the teacher's are decisions** | The agent judges free-form answers and quotes the student's words; outcomes are suggestions the teacher confirms before a student sees them |
| Not every event is an alert: **triage** decides log, summarise or alert | Teachers get meaningful signals; a wellbeing concern or a student's own request always comes through (`agent/triage.py`) |
| Memory is an **evidence ledger**, not a learner profile | Storing, retrieving and personalising are separate: past lessons are retrieved and logged, but only change teaching when the lesson allows it |
| Misuse is reported as an **observation** | The system reports what it saw ("asked the agent to hand over the work"), never an inferred intent |
| Identity is **pseudonymous by construction** | No real name enters this database at all |
| The lesson brief is **teacher-approved data** | Teacher authority is data, versioned: changing an approved lesson makes a new draft |

## Requirements

Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+, and Docker. The database is
PostgreSQL **18.6**, supplied by the container below — no local Postgres install is needed.

## Database

The database runs in **its own Docker container** and nothing else lives on that
server. That isolation is deliberate: this is a school pilot, so the student
database must not share a server with unrelated projects, must be destroyable and
rebuildable without touching anything else, and must be reproducible from this
repository alone.

```bash
docker compose up -d          # Postgres 18 on host port 5433
```

It creates two databases, `genai4ed` and `genai4ed_test`, both locked to the
`genai4ed` role. Host port 5432 belongs to the machine's own Postgres server and
is not used by this project.

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose stop` |
| Logs | `docker compose logs -f db` |
| Throw it away and start clean | `docker compose down -v && docker compose up -d` |
| psql inside the container | `docker exec -it genai4ed-db psql -U genai4ed -d genai4ed` |

Note for anyone editing `docker-compose.yml`: postgres:18 wants a single volume
mount at `/var/lib/postgresql`. The `/var/lib/postgresql/data` form that every
pre-18 example shows makes the container refuse to start.

## Run

```bash
cp .env.example .env                      # add OPENROUTER_API_KEY for a real model
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload      # http://localhost:8000
```

```bash
cd frontend
npm install
npm run dev                               # http://127.0.0.1:3000
```

Open <http://127.0.0.1:3000> and pick who to be. The browser calls `/api` on
the same address it loaded the page from, and Next forwards those calls to the
backend (`next.config.ts`). One address serving everything is what lets a
single tunnel share the whole app.

**The model.** With `OPENROUTER_API_KEY` set, the class agent is a real model through OpenRouter
(`OPENROUTER_MODEL`, default `anthropic/claude-sonnet-5`). Without one, a scripted demo agent answers
instead: every other part of the loop - rules, checks, triage, evidence, the teacher's view - is the
same, but its replies are canned and it doesn't really understand what students write.

**Trying it.** With demo sign-in on (the default), any name and password get in. Sign in as a teacher
in one browser and a student in a private window - sign the student in first so they join the
teacher's class. Teachers also get a **walkthrough** bar that runs a lesson with six pretend students.

Health: `GET /health` is liveness (touches nothing); `GET /health/ready` is readiness and returns 503
while the database is unreachable.

## Look at the data

The seed creates a teacher, a class with join codes, the sample lessons and one lesson running, but
no student work. The quickest way to fill the tables is the walkthrough (sign in as a demo teacher),
or talk to the agent as a student.

```bash
cd backend
uv run python -m app.seed --reset   # teacher, class 10B, sample lessons, one running
```

Then browse it. Two VS Code extensions are set up for this:

- **PostgreSQL** (`ms-ossdata.vscode-pgsql`) — object explorer and query editor.
  Add a connection: server `localhost`, port **5433**, database `genai4ed`, user `genai4ed`,
  password `genai4ed`. Only this project's databases are on that server.

[`sql/inspect.sql`](sql/inspect.sql) holds the queries worth running — the approved briefs, a
student's conversation, the evidence ledger, rule compliance per agent turn, what reached the
teacher, and the S5 feasibility metrics in one statement.
With a SQLTools connection active, put the cursor in a statement and press `Ctrl+E Ctrl+E`.

pgAdmin 4 also ships with PostgreSQL; its **Generate ERD** (right-click the database) draws
the whole schema with foreign keys.

## Sending it to someone else

The whole platform is three containers. A recipient needs Docker Desktop and
nothing else - no Python, no Node, no Postgres, no database setup.

1. Send them this repository as a zip (or a git clone).
2. They run, from the folder:

```bash
docker compose up -d
```

3. After a few minutes: the app is at <http://localhost:3000>, the API at
   <http://localhost:8000/docs>. Migrations are applied automatically on start.

To load the sample lessons so there is something to look at (demo sign-in does this per teacher
anyway):

```bash
docker compose exec api uv run python -m app.seed
```

To stop, and to remove every trace including the data:

```bash
docker compose down          # stop, keep the data
docker compose down -v       # stop and destroy the database volume
```

Ports collide with something already running? Override without editing anything:
`WEB_PORT=3100 API_PORT=8100 DB_PORT=5533 docker compose up -d`.

### Showing it to someone over the internet

No domain, so this uses a Cloudflare **quick tunnel**: a temporary public link to
the app running on this laptop. Install `cloudflared` once:

```powershell
winget install --id Cloudflare.cloudflared
```

Then, for each demo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\share.ps1        # start app + tunnel
powershell -ExecutionPolicy Bypass -File scripts\share.ps1 -Stop  # afterwards
```

The script starts Docker if needed, rebuilds and starts the stack from the
current code, and prints a `https://....trycloudflare.com` link. The link
changes every run. Ctrl+C closes it.

**The link has no login.** The app trusts whatever pseudonym the browser sends,
so anyone holding the link can act as any teacher or student. Send it directly
to the person you are showing, close it when you are done, and never let real
data near it. A proper sign-in in front of it needs a domain on Cloudflare
(Tunnels plus Cloudflare Access) - the route to take before the pilot.

### If their network blocks Docker Hub

Some school networks do. Then export the built images instead and send those
alongside the repo - larger, and it has to be redone for every change:

```bash
docker compose build
docker save genai4ed-api genai4ed-web postgres:18 -o genai4ed-images.tar
# they run: docker load -i genai4ed-images.tar && docker compose up -d
```

Worth asking their IT before assuming either way.

### Before it meets an actual student

This packaging is for internal use and demonstration. A classroom deployment
still needs the S7 boundary decisions settled - hosting, identity, retention,
approved data path - plus TLS, real authentication in place of the development
identity header, a backup story for the database volume, and the DPO and ethics
approvals. None of that is in this compose file, deliberately: it is not
pretending to be production.

## Test

```bash
cd backend
uv run pytest        # never calls a model: the suite forces the scripted client
uv run ruff check .
```

```bash
cd frontend
npx tsc --noEmit && npm run lint
```

Always drive Python through `uv run …` rather than an activated virtualenv; venv launcher scripts on
Windows break as soon as the folder moves.

## Layout

```text
backend/app/
  agent/
    llm.py           LLMClient: OpenRouterClient | ScriptedClient     ← model seam
    brief.py         the lesson brief the teacher approves
    policy.py        the teacher's rules, compiled and read back
    context.py       what the agent is shown, per conversation        ← isolation boundary
    memory.py        retrieval from a student's earlier lessons      ← retrieval seam
    supervisor.py    checks every reply to a student; screens student messages
    triage.py        log | summarise | alert
    teacher_mode.py  designing a lesson with the teacher
    student_mode.py  teaching one student, one turn
    classroom.py     the class pulse, questions about the class, outcomes
    materials.py     reading PDFs, Word, PowerPoint, text; images go to the model
    scripted.py      the demo agent used with no API key
  routers/
    designs.py       teacher ↔ agent: the lesson studio
    learn.py         student ↔ agent: the lesson
    live.py          the teacher's live view, student drawer, guidance, review
    lessons.py       booking and starting a lesson for a class
    teacher.py       classes, join codes, pause/resume/end, alerts
    walkthrough.py   the demo walkthrough's pretend class
  auth.py            pseudonymous identity, roles, isolation guards
  ledger.py          append-only evidence records
  events.py          in-process broker behind SSE                     ← realtime seam
frontend/app/
  teacher/           home (what do you want to teach?), studio, live lesson, review, classes
  student/           the lesson as a conversation
```

`LLMClient`, `context`, `memory`, `supervisor` and `triage` are the replaceable parts a research
configuration changes (concept note §3): a different model, a different context policy, retrieval with
or without personalisation, stricter checks, different escalation.
