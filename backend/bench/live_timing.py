"""Baseline: wall time of the teacher's read endpoints on the live local stack, as a browser
would see them. Read-only GETs, repeated; median, p95 and max in ms, plus the body size.
From backend/, with the containers up:

    uv run python bench/live_timing.py [teacher ...]

The numbers also go to bench/out/live_timing.json (ignored by git)."""

import json
import pathlib
import statistics
import sys
import time

import httpx

API = "http://127.0.0.1:8000"
RUNS = 10


def timed(c: httpx.Client, path: str) -> tuple[list[float], int]:
    c.get(path)  # warm
    times = []
    size = 0
    for _ in range(RUNS):
        t0 = time.perf_counter()
        r = c.get(path)
        times.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        size = len(r.content)
    return times, size


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(0.95 * (len(xs) - 1)))]


def main(teachers: list[str]) -> None:
    out = {}
    for teacher in teachers:
        c = httpx.Client(base_url=API, timeout=60)
        r = c.post("/api/auth/demo", json={"role": "teacher", "username": teacher, "password": "x"})
        r.raise_for_status()
        classes = c.get("/api/teacher/classes").json()
        rows = classes if isinstance(classes, list) else classes.get("classes", [])
        paths = ["/api/teacher/thread", "/api/teacher/thread/lessons", "/api/teacher/classes"]
        for k in rows[:2]:
            cid = k["id"]
            paths += [
                f"/api/teacher/classes/{cid}/progress",
                f"/api/teacher/classes/{cid}/students",
            ]
        print(f"\n{teacher}: {len(rows)} classes")
        print(f"{'path':58} {'median':>8} {'p95':>8} {'max':>8} {'bytes':>8}")
        for path in paths:
            times, size = timed(c, path)
            med, hi, mx = statistics.median(times), p95(times), max(times)
            print(f"{path:58} {med:8.0f} {hi:8.0f} {mx:8.0f} {size:8d}")
            out[f"{teacher} {path}"] = {"median_ms": round(med), "p95_ms": round(hi), "bytes": size}
        c.close()
    out_path = pathlib.Path(__file__).resolve().parent / "out" / "live_timing.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["teacher-1", "bench-t"])
