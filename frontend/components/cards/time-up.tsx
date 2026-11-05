"use client";

import { useState } from "react";
import type { StripRow } from "@/lib/api";
import type { Act } from "@/components/cards/parts";
import { Button, minutesUntil, useClockNow } from "@/components/ui";

/** When a running class's time runs out, this takes the middle of the teacher's screen,
 * whatever they were looking at: end the lesson, or add minutes. "Decide later" puts it
 * away for that class; the pupils wait either way, with their boxes closed. */
export function TimeUpDialog({ rows, act, busy }: { rows: StripRow[]; act: Act; busy: boolean }) {
  const now = useClockNow();
  const [later, setLater] = useState<Set<string>>(() => new Set());
  const [minutes, setMinutes] = useState("10");
  const due = rows.find(
    (r) => r.status === "open" && minutesUntil(r.closes_at, now) === 0 && !later.has(r.session_id),
  );
  if (!due) return null;
  const n = Math.max(1, Math.min(120, Math.round(Number(minutes) || 0)));
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="time-up-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-6"
    >
      <div className="w-full max-w-md rounded-[var(--radius-sheet)] border border-rule bg-sheet px-7 py-7 shadow-xl">
        <p className="text-xs font-semibold tracking-wide text-red-pen uppercase">Time&apos;s up</p>
        <h2 id="time-up-title" className="mt-1 font-serif text-2xl font-semibold text-ink">
          {due.class_label} · {due.title}
        </h2>
        <p className="mt-2 text-sm text-pencil">
          The pupils&apos; boxes are closed while you decide. End the lesson, or give them more time.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act({ action: "extend", session_id: due.session_id, minutes: n });
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
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-rule pt-4">
          <Button
            variant="red"
            disabled={busy}
            onClick={() => act({ action: "end", session_id: due.session_id })}
          >
            End the lesson
          </Button>
          <Button
            variant="plain"
            onClick={() => setLater((s) => new Set(s).add(due.session_id))}
          >
            Decide later
          </Button>
        </div>
      </div>
    </div>
  );
}
