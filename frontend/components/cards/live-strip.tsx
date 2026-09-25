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
    <div className="no-print sticky top-[var(--walkthrough-h,0px)] z-40 border-b border-rule bg-sunken">
      {rows.map((row) => {
        const names = [...new Set(row.needs_you.map((a) => a.pseudonym))];
        const need = names.length;
        return (
          <div
            key={row.session_id}
            className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 text-sm sm:px-6"
          >
            <span className="font-semibold text-ink">{row.class_label}</span>
            <span className="min-w-0 truncate text-pencil">{row.title}</span>
            {row.status === "paused" && <span className="font-semibold text-amber">Paused</span>}
            {need > 0 ? (
              <span className="font-bold text-red-pen">
                {names.join(", ")}
                {row.needs_you_more > 0 && ` and ${row.needs_you_more} more`} need
                {need === 1 && !row.needs_you_more ? "s" : ""} you
              </span>
            ) : (
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
        );
      })}
    </div>
  );
}
