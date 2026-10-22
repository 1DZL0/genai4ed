"use client";

import type { ReactNode } from "react";
import type { ClassCard, ThreadAction } from "@/lib/api";

/** The pieces every card is made of, and the words and colours for a student's state. */

/** What a button on a card does. Every one is the teacher's, not the agent's. */
export type Act = (action: ThreadAction) => Promise<void>;

export type StudentState = ClassCard["students"][number]["state"];

export function Sheet({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
      {children}
    </div>
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="py-2">
      <p className="text-xs font-bold text-pencil">{label}</p>
      <div className="mt-1 text-sm text-ink">{children}</div>
    </div>
  );
}

export const STATE_WORDS: Record<StudentState, string> = {
  needs_you: "Needs you",
  struggling: "Struggling",
  working: "Working",
  finished: "Finished",
  not_started: "Not started",
  took_part: "Took part",
};

/* One colour per state, the same on the board, the strip, a student's card and Research:
   red needs you, amber struggling, blue working, green finished. Always beside its word. */

/** A student's tile: a tinted ground and a border in the state's colour. */
export const STATE_LOOK: Record<StudentState, string> = {
  needs_you: "border-red-pen/60 bg-red-pen-wash",
  struggling: "border-amber/50 bg-amber-wash",
  working: "border-progress/40 bg-progress-wash",
  finished: "border-tick/50 bg-tick-wash",
  not_started: "border-rule bg-sunken",
  took_part: "border-rule-strong bg-sheet",
};

export const STATE_TEXT: Record<StudentState, string> = {
  needs_you: "text-red-pen",
  struggling: "text-amber",
  working: "text-progress",
  finished: "text-tick",
  not_started: "text-faint",
  took_part: "text-ink",
};

export const STATE_DOT: Record<StudentState, string> = {
  needs_you: "bg-red-pen",
  struggling: "bg-amber",
  working: "bg-progress",
  finished: "bg-tick",
  not_started: "bg-rule-strong",
  took_part: "bg-pencil",
};

const STATE_PILL: Record<StudentState, string> = {
  needs_you: "bg-red-pen-wash text-red-pen",
  struggling: "bg-amber-wash text-amber",
  working: "bg-progress-wash text-progress",
  finished: "bg-tick-wash text-tick",
  not_started: "bg-sunken text-faint",
  took_part: "bg-sunken text-ink",
};

/** A state as a small rounded label: a dot and the word, with a count in front if given. */
export function StatePill({ state, count }: { state: StudentState; count?: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATE_PILL[state]}`}
    >
      <span aria-hidden="true" className={`size-2 rounded-full ${STATE_DOT[state]}`} />
      {count !== undefined && <span className="figures">{count}</span>}
      {count !== undefined ? STATE_WORDS[state].toLowerCase() : STATE_WORDS[state]}
    </span>
  );
}

// Classes told apart at a glance by a colour of their own, picked from the label so it
// never changes. Muted, and never one of the state colours.
const CLASS_COLOURS = ["#7b4397", "#19817f", "#b4632a", "#b83a6e", "#56607a", "#8a6d12"];

export function classColour(label: string): string {
  let h = 0;
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return CLASS_COLOURS[h % CLASS_COLOURS.length];
}

/** A class's name with its colour dot. */
export function ClassName({ label, className = "" }: { label: string; className?: string }) {
  return (
    <span className={`inline-flex items-baseline gap-1.5 ${className}`}>
      <span
        aria-hidden="true"
        className="inline-block size-2.5 shrink-0 translate-y-[1px] rounded-full"
        style={{ backgroundColor: classColour(label) }}
      />
      {label}
    </span>
  );
}
