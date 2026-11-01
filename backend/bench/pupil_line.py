"""One message for the pupil on camera in the demo video, written by the bench's pupil writer
from a persona, a beat and the conversation so far, so what they say answers what the tutor
actually asked. tools/video/record.py runs it once per turn, from backend/:

    echo '{"session": "...", "who": "...", "beat": "...", "lines": [...]}' \
        | uv run python -m bench.pupil_line

Prints the pupil's message and nothing else on stdout. "voice" may say who is being played
("a Year 9 pupil, 13 years old"); "lines" are {"who": "agent" | "student", "text": ...} as the
learn API gives them; "must" is text the line has to contain, as a string or a list of
alternatives (any one of). A line that would not do on camera (nothing came back, a grown-up
tone, too long, the must missing) is tried again, up to three times, and a call that errors is
retried too; if none will do the last is printed and the exit code is 3, so the recorder can
fall back to a line of its own.
"""

import asyncio
import json
import sys

import httpx

from app.db import get_engine
from bench.live_pupils import brief_of
from bench.run_bench import PUPIL_MODEL, Beat, Persona, PupilWriter, cheat_sheet

TRIES = 3
# The characters, written as code points so no dash is in this source: what a kid would not type.
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
NOT_A_KID = ("!", EM_DASH, EN_DASH, "sorry", "as an ai", "i believe", "therefore")


def wrong_with(text: str, must=()) -> str | None:
    """Why a line will not do on camera, or None when it will. "must" is what the beat has to
    contain: a string, or a list of alternatives any one of which is enough."""
    low = text.lower()
    if not text or text == "um i dont know":  # the writer's own stand-in for an empty reply
        return "nothing came back"
    if any(mark in low for mark in NOT_A_KID):
        return "tone"
    if "\n" in text:
        return "more than one line"
    if len(text.split()) > 22:
        return "too long"
    wants = [must] if isinstance(must, str) else list(must)
    if wants and not any(w in text for w in wants):
        return f"none of {wants} in it"
    return None


async def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ask = json.loads(sys.stdin.read())
    writer = PupilWriter(
        PUPIL_MODEL, cheat_sheet(await brief_of(ask["session"])), voice=ask.get("voice")
    )
    persona = Persona("on camera", ask["who"], [])
    beat = Beat("say", ask["beat"])
    text, why = "", "not tried"
    try:
        for attempt in range(1, TRIES + 1):
            try:
                text = await writer.write(persona, beat, ask["lines"])
            except (httpx.HTTPError, httpx.TimeoutException) as e:  # a 429 or a slow call
                why = f"call failed: {type(e).__name__}"
                print(f"try {attempt}: {why}", file=sys.stderr)
                await asyncio.sleep(2)
                continue
            why = wrong_with(text, ask.get("must", ()))
            if why is None:
                break
            print(f"try {attempt}: {why}: {text!r}", file=sys.stderr)
    finally:
        await writer.client.aclose()
        await get_engine().dispose()
    print(text)
    return 0 if why is None else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
