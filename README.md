# GenAI4ED — Teacher-Governed Personal AI Tutors

Internal prototype for the GenAI4ED pilot

One auditable monolith: a teacher authors and activates a **lesson contract**, opens a timed **session**,
and each student gets a logically separate tutor that may give **only the next permitted rung of help**.
Separation between students is state, permissions and logs — not separate processes.

> **Not for student use.** School/DPO review, ethics approval, age-appropriate information, and parental
> authorisation or student assent must all be settled first (concept note §4, §7). Nothing here should be
> pointed at a real class until that concludes.

## Design commitments

These are load-bearing. Changing one is a design decision, not a refactor.

| Commitment | Why |
| --- | --- |
| The assistance ladder is enforced **server-side**, after generation | TASD: "no direct answers" prompting reduced but did not eliminate answer leakage across 878 students |
| Correctness is decided by **deterministic grading**, never by the model | The LLM's job is how to help, not whether the student is right |
| Durable memory is an **evidence ledger**, not a learner profile | A recurring misconception is a runtime inference with citations and confidence, never a permanent characterisation of a child |
| Policy breaches are reported as observable **assistance-policy conflicts** | The system reports what it saw; it does not claim to infer cheating intent |
| Identity is **pseudonymous by construction** | No real name enters this database at all |
| Ladder, thresholds and material are **teacher-authored data** | Teacher authority is data, not constants in code |

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
cp .env.example .env                      # every default works; no API key needed
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload      # http://localhost:8000
```

```bash
cd frontend
npm install
npm run dev                               # http://127.0.0.1:3000
```

Open <http://127.0.0.1:3000> and pick who to be. Use `127.0.0.1` rather than
`localhost`: they are different origins to a browser, and only the loopback
addresses listed in `CORS_ORIGINS` are allowed.

To drive both sides at once, open two windows with `?as=` on each URL:

```
http://127.0.0.1:3000/student/<session-id>?as=10B-01
http://127.0.0.1:3000/teacher/<session-id>?as=teacher-01
```

Answer wrongly three times as the student and watch the teacher's queue fill.
`?as=` is a development convenience and grants nothing: the backend already
trusts whatever pseudonym the browser sends, which is exactly why this build
must not meet a real class.

Health: `GET /health` is liveness (touches nothing); `GET /health/ready` is readiness and returns 503
while the database is unreachable.

## Look at the data

The seed creates a contract and an open session but no student work, so the
interesting tables start empty. To fill them with a realistic lesson:

```bash
cd backend
uv run python -m app.seed --reset   # teacher, class, contract, four items, open session
uv run python -m app.demo           # a lesson: ladder escalation, a withheld leak, a help request
```

Then browse it. Two VS Code extensions are set up for this:

- **PostgreSQL** (`ms-ossdata.vscode-pgsql`) — object explorer and query editor.
  Add a connection: server `localhost`, port **5433**, database `genai4ed`, user `genai4ed`,
  password `genai4ed`. Only this project's databases are on that server.

[`sql/inspect.sql`](sql/inspect.sql) holds the queries worth running — policy compliance,
the evidence ledger, the teacher's queue, and the S5 feasibility metrics in one statement.
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

To load a demonstration lesson so there is something to look at:

```bash
docker compose exec api uv run python -m app.seed
docker compose exec api uv run python -m app.demo
```

To stop, and to remove every trace including the data:

```bash
docker compose down          # stop, keep the data
docker compose down -v       # stop and destroy the database volume
```

Ports collide with something already running? Override without editing anything:
`WEB_PORT=3100 API_PORT=8100 DB_PORT=5533 docker compose up -d`.

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
uv run pytest        # green with no API key set — the stub provider is the default
uv run ruff check .
```

Always drive Python through `uv run …` rather than an activated virtualenv; venv launcher scripts on
Windows break as soon as the folder moves.

## Layout

```text
backend/app/
  auth.py          pseudonymous identity, role and cross-student isolation guards
  grading.py       deterministic normalised matching        ← grader seam
  ledger.py        append-only evidence records
  events.py        in-process broker behind SSE             ← realtime seam
  retention.py     purge job, two retention classes
  research/        structured export + condition seam (no conditions defined yet)
  tutor/
    memory.py      MemoryProvider — evidence card | NullMemoryProvider
    policy.py      TutorPolicy — ladder read from the contract, pure, no I/O
    supervisor.py  Supervisor — accept | regenerate | withhold
    providers.py   LLMProvider + deterministic StubProvider
    service.py     the per-turn pipeline
frontend/app/      student session view, teacher console
```

`MemoryProvider`, `TutorPolicy`, `Supervisor` and `LLMProvider` are the four replaceable modules the
concept note requires for research configuration (§3).
