"""Run the teacher test set: realistic teacher messages to the class agent, on the real model.

Run it on every change to the teacher's prompt, from backend/, with the database container up:

    uv run python -m bench.teacher_set                      the whole set
    uv run python -m bench.teacher_set --label v25 --against v24
    uv run python -m bench.teacher_set --only class,rename  a group, a state, a rule or case ids
    uv run python -m bench.teacher_set --prompt bare        the prompt with its rules taken out
    uv run python -m bench.teacher_set --prompt without:class   one module left out
    uv run python -m bench.teacher_set --prompt draft.txt   a prompt from a file
    uv run python -m bench.teacher_set --repeat 3 --only essay-full

It costs real money: one model reply per case, on the model and key in the repo's .env. It uses
its own database (genai4ed_eval, made if missing, emptied at the start), never the live one or
the tests'. Results go to bench/out/<label>.json, and <label>.txt holds every reply to read.

The cases and what each must pass are in bench/teacher_cases.py. Every check names a rule, so
the failures of a run say which rules the prompt is missing; `--prompt bare` shows which rules
the model keeps with no prompt at all, and those are the ones a prompt does not need to state.
`--prompt without:<module>` leaves one module of app/agent/teacher_prompt.py out: the rules
that then fail are why that module is there, and a module nothing fails without comes out.
"""

import argparse
import asyncio
import os
from pathlib import Path

EVAL_DATABASE_URL = "postgresql+asyncpg://genai4ed:genai4ed@127.0.0.1:5433/genai4ed_eval"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the teacher test set on the real model.")
    parser.add_argument("--only", default="", help="groups, states, rules or case ids, by comma")
    parser.add_argument(
        "--prompt", default="", help="'bare', 'without:<module>', or a file holding the prompt"
    )
    parser.add_argument("--repeat", type=int, default=1, help="times to run each case")
    parser.add_argument("--label", default="", help="the name the results are saved under")
    parser.add_argument("--against", default="", help="an earlier label, to list what changed")
    parser.add_argument("--together", type=int, default=6, help="cases running at once")
    return parser.parse_args()


def _set_environment() -> None:
    """Before the app is imported: it reads its settings once. The key and the model are left
    to the repo's .env; everything that decides what the run touches is set here."""
    os.environ["DATABASE_URL"] = os.environ.get("GENAI4ED_EVAL_DATABASE_URL", EVAL_DATABASE_URL)
    os.environ["DEV_IDENTITY_ENABLED"] = "true"
    os.environ["SUPERVISOR_ENFORCE"] = "true"
    os.environ["STUDY_ACTIVE"] = "false"
    os.environ["PROMPTS"] = "full"
    os.environ["COOKIE_SECURE"] = "false"
    os.environ["DEMO_SIGN_IN"] = "false"
    # A line per request would bury the results; LOG_LEVEL=INFO brings them back.
    os.environ.setdefault("LOG_LEVEL", "ERROR")


def main() -> None:
    args = _arguments()
    _set_environment()
    from app.agent import thread
    from app.agent.teacher_prompt import MODULES
    from bench import teacher_run
    from bench.teacher_cases import CASES

    wanted = {w.strip() for w in args.only.split(",") if w.strip()}
    cases = [
        c
        for c in CASES
        if not wanted or wanted & {c.id, c.group, c.state, *(k.rule for k in c.checks)}
    ]
    if not cases:
        raise SystemExit(f"No case matches {args.only!r}.")

    prompt = "the app's"
    if args.prompt == "bare":
        # Who the agent is and nothing else: what it does unprompted is what needs no rule.
        thread.SYSTEM = MODULES["who"]
        prompt = "bare"
    elif args.prompt.startswith("without:"):
        left_out = args.prompt.removeprefix("without:")
        if left_out not in MODULES:
            raise SystemExit(f"No module {left_out!r}: there are {', '.join(MODULES)}.")
        thread.SYSTEM = "\n".join(text for name, text in MODULES.items() if name != left_out)
        prompt = f"without {left_out}"
    elif args.prompt:
        thread.SYSTEM = Path(args.prompt).read_text(encoding="utf-8")
        prompt = args.prompt
    label = args.label or (Path(prompt).stem if args.prompt else "run")

    async def go() -> list[dict]:
        name = await teacher_run.prepare_database()
        print(
            f"{len(cases)} cases x {args.repeat} on {teacher_run.real_client().model}, "
            f"prompt: {prompt} ({len(thread.SYSTEM):,} characters), database: {name}"
        )
        return await teacher_run.run(cases, repeat=args.repeat, together=args.together)

    rows = asyncio.run(go())
    path = teacher_run.save(label, rows, prompt=prompt)
    earlier = teacher_run.load(args.against) if args.against else None
    print()
    print(teacher_run.summary(rows, earlier))
    print(f"\nSaved: {path} (and the replies, to read, in {path.with_suffix('.txt').name})")


if __name__ == "__main__":
    main()
