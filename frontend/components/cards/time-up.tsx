"use client";

import { useState } from "react";
import type { StripRow } from "@/lib/api";
import type { Act } from "@/components/cards/parts";
import { Button, minutesUntil, useClockNow } from "@/components/ui";

/** How many minutes before the end the teacher is asked what to do: the same moment the
 * pupils' clock turns amber. */
const WARN_AT = 5;

/** The lesson clock asks the teacher, in the middle of the screen whatever they were looking
 * at, twice: once when a running class has five minutes left, and again when its time runs
 * out. Each time they can add minutes, pause the class (the clock stops) or end the lesson.
 * "Keep going" puts the warning away for that class; "Decide later" does the same at zero, where
 * the pupils wait with their boxes closed either way. */
export function TimeUpDialog({ rows, act, busy }: { rows: StripRow[]; act: Act; busy: boolean }) {
  const now = useClockNow();
  const [later, setLater] = useState<Set<string>>(() => new Set());
  const [warned, setWarned] = useState<Set<string>>(() => new Set());
  const [minutes, setMinutes] = useState("10");
  const running = rows.filter((r) => r.status === "open");
  const due = running.find(
    (r) => minutesUntil(r.closes_at, now) === 0 && !later.has(r.session_id),
  );
  const soon = running.find((r) => {
    const left = minutesUntil(r.closes_at, now);
    return left !== null && left > 0 && left <= WARN_AT && !warned.has(r.session_id);
  });
  const row = due ?? soon;
  if (!row) return null;
  const left = minutesUntil(row.closes_at, now) ?? 0;
  const n = Math.max(1, Math.min(120, Math.round(Number(minutes) || 0)));
  const id = row.session_id;
  // Whatever the teacher does about the warning, it is not asked again for this lesson.
  const answer = (then: () => void) => () => {
    if (!due) setWarned((s) => new Set(s).add(id));
    then();
  };
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="time-up-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-6"
    >
      <div className="w-full max-w-lg rounded-[var(--radius-sheet)] border border-rule bg-sheet px-7 py-7 shadow-xl">
        <p
          className={`text-xs font-semibold tracking-wide uppercase ${due ? "text-red-pen" : "text-amber"}`}
        >
          {due ? "Time's up" : `${left} minute${left === 1 ? "" : "s"} left`}
        </p>
        <h2 id="time-up-title" className="mt-1 font-serif text-2xl font-semibold text-ink">
          {row.class_label} · {row.title}
        </h2>
        <p className="mt-2 text-sm text-pencil">
          {due
            ? "The pupils' boxes are closed while you decide. Give them more time, pause the class, or end the lesson."
            : "The pupils' boxes close when the time runs out. Give them more time, pause the class, or end the lesson now."}
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            answer(() => act({ action: "extend", session_id: id, minutes: n }))();
          }}
          className="mt-5 flex flex-wrap items-center gap-2"
        >
          <label className="sr-only" htmlFor="time-up-minutes">
            Minutes to add
          </label>
          <input
            id="time-up-minutes"
            type="number"
            min={1}
            max={120}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
            className="figures h-10 w-20 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-base text-ink"
          />
          <span className="text-sm text-pencil">minutes</span>
          <Button type="submit" disabled={busy}>
            Add time
          </Button>
        </form>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-rule pt-4">
          <Button
            variant="quiet"
            disabled={busy}
            onClick={answer(() => act({ action: "pause", session_id: id }))}
          >
            Pause the class
          </Button>
          <Button
            variant="red"
            disabled={busy}
            onClick={answer(() => act({ action: "end", session_id: id }))}
          >
            End the lesson
          </Button>
          <Button
            variant="plain"
            className="ml-auto"
            onClick={
              due
                ? () => setLater((s) => new Set(s).add(id))
                : answer(() => undefined)
            }
          >
            {due ? "Decide later" : "Keep going"}
          </Button>
        </div>
      </div>
    </div>
  );
}
