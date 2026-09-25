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

export const STATE_LOOK: Record<StudentState, string> = {
  needs_you: "border-red-pen/60",
  struggling: "border-amber/50",
  working: "border-rule-strong",
  finished: "border-tick/50",
  not_started: "border-rule",
  took_part: "border-rule-strong",
};

export const STATE_TEXT: Record<StudentState, string> = {
  needs_you: "text-red-pen",
  struggling: "text-amber",
  working: "text-ink",
  finished: "text-tick",
  not_started: "text-faint",
  took_part: "text-ink",
};
