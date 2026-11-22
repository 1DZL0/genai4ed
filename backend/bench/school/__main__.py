"""`uv run python -m bench.school ...`: runs a school day on the test copy (see run.py)."""

import asyncio
import sys

from bench.school.run import main

sys.exit(asyncio.run(main()))
