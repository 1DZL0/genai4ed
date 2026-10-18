"use client";

import type { StripRow } from "@/lib/api";
import type { Act } from "@/components/cards/parts";
import { TimeLeft } from "@/components/ui";

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
            <span className="font-semibold text-ink">{row.class_label}</span>
            <span className="min-w-0 truncate text-pencil">{row.title}</span>
            {row.status === "paused" && <span className="font-semibold text-amber">Paused</span>}
            {row.needs_you.length === 0 && (
              <span className="text-pencil">
                {row.counts.working ?? 0} working · {row.counts.finished ?? 0} finished
              </span>
            )}
            <span className="ml-auto flex items-center gap-3">
              <TimeLeft closesAt={row.closes_at} status={row.status} />
              {showingSession === row.session_id ? (
                <span className="text-pencil">On screen</span>
              ) : (
                <button
                  disabled={busy}
                  onClick={() => act({ action: "show_class", session_id: row.session_id })}
                  className="font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                >
                  Show the class
                </button>
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
                    className="font-bold text-red-pen underline decoration-red-pen/40 underline-offset-4 hover:decoration-red-pen"
                  >
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
