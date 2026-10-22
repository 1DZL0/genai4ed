"use client";

import type { StripRow } from "@/lib/api";
import { ClassName, StatePill, type Act } from "@/components/cards/parts";
import { Button, TimeLeft } from "@/components/ui";

/* ---------- the strip: who needs you, always there ---------- */

export function LiveStrip({
  rows,
  act,
  busy,
  showingSession,
}: {
  rows: StripRow[];
  act: Act;
  busy: boolean;
  /** The class already on screen: the strip doesn't offer to show it again. */
  showingSession?: string | null;
}) {
  if (rows.length === 0) return null;
  return (
    <div className="no-print sticky top-0 z-40 border-b border-rule bg-sunken">
      {rows.map((row) => (
        <div key={row.session_id} className="w-full px-4 py-1.5 text-sm sm:px-6">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <ClassName label={row.class_label} className="font-semibold text-ink" />
            <span className="min-w-0 truncate text-pencil">{row.title}</span>
            {row.status === "paused" && <span className="font-semibold text-amber">Paused</span>}
            {row.needs_you.length === 0 && (
              <span className="flex flex-wrap gap-1.5">
                <StatePill state="working" count={row.counts.working ?? 0} />
                <StatePill state="finished" count={row.counts.finished ?? 0} />
              </span>
            )}
            <span className="ml-auto flex items-center gap-3">
              <TimeLeft closesAt={row.closes_at} status={row.status} />
              {showingSession === row.session_id ? (
                <span className="text-pencil">On screen</span>
              ) : (
                <Button
                  size="sm"
                  variant="pill"
                  disabled={busy}
                  onClick={() => act({ action: "show_class", session_id: row.session_id })}
                >
                  Show the class
                </Button>
              )}
            </span>
          </div>
          {row.needs_you.length > 0 && (
            <ul className="mt-1 space-y-1" aria-label="Students who need you">
              {row.needs_you.map((a) => (
                <li key={a.exception_id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <button
                    disabled={busy}
                    onClick={() =>
                      act({
                        action: "show_student",
                        session_id: row.session_id,
                        student_id: a.student_id,
                      })
                    }
                    className="inline-flex items-center gap-1.5 rounded-full border border-red-pen/40 bg-red-pen-wash px-3 py-0.5 font-bold text-red-pen hover:border-red-pen"
                  >
                    <span aria-hidden="true" className="size-2 rounded-full bg-red-pen" />
                    {a.pseudonym} needs you
                  </button>
                  <span className="min-w-0 flex-1 truncate text-ink">{a.summary}</span>
                  <button
                    disabled={busy}
                    onClick={() => act({ action: "acknowledge", exception_id: a.exception_id })}
                    className="rounded-full border border-rule-strong bg-sheet px-3 py-0.5 text-xs font-semibold text-ink hover:border-ink"
                  >
                    Dealt with
                  </button>
                </li>
              ))}
              {row.needs_you_more > 0 && (
                <li className="text-pencil">and {row.needs_you_more} more on the class card</li>
              )}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
