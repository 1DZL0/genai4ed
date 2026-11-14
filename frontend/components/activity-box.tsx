"use client";

import { useState } from "react";

import type { Activity, ChatActivity } from "@/lib/api";

/**
 * The activity box: the headings a teacher presses to say what kind of activity they are
 * assigning. It sits above the typing box. One, several or none can be pressed; what is pressed
 * goes beside the teacher's next message, never typed into it. Only headings are offered: the
 * kind of activity under a heading is the agent's to work out and say in words.
 */

/** The line the server keeps under the teacher's words when they pressed a heading. Said the
 * same way in the bubble that stands in until the server has answered. Mirrors picked_line in
 * backend/app/agent/activities.py, which is the source of truth. */
export function pickedLine(labels: string[]): string {
  return labels.length ? `The activity I picked: ${labels.join(", ")}.` : "";
}

// A heading the teacher pressed is filled in the site's main colour. One the agent worked out
// is in the colour the lesson card uses for what the agent wrote itself, and says "guess" in
// words, so the two never differ by colour alone.
const PICKED = "border-accent bg-accent text-white";
const GUESSED = "border-amber/50 bg-amber-wash text-amber";
const UNPRESSED = "border-rule-strong bg-sheet text-ink hover:border-ink";
const BADGE = "rounded-full bg-accent/10 px-2 py-0.5 text-xs font-normal text-accent";

export function ActivityBox({
  offered,
  shown,
  guess,
  waiting,
  open,
  onPress,
  onOpen,
}: {
  /** What can be pressed, in the screen's order. */
  offered: Activity[];
  /** The keys of the headings that are highlighted. */
  shown: string[];
  /** The highlighted headings were worked out by the agent, not pressed by the teacher. */
  guess: boolean;
  /** Pressed and not sent yet: it goes with the next message. */
  waiting: boolean;
  open: boolean;
  onPress: (key: string) => void;
  onOpen: (open: boolean) => void;
}) {
  if (offered.length === 0) return null;
  const marked = offered.filter((a) => shown.includes(a.key));

  if (!open)
    return (
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-1.5 text-sm text-ink">
        <span className="font-semibold">Activity</span>
        {marked.length === 0 && <span className="text-pencil">none picked</span>}
        {marked.map((a) => (
          <span
            key={a.key}
            className={`rounded-full border px-2 py-0 text-xs leading-5 ${guess ? GUESSED : PICKED}`}
          >
            {a.label}
            {guess && <span className="font-semibold"> guess</span>}
          </span>
        ))}
        {waiting && <span className={BADGE}>sent with your message</span>}
        <button
          type="button"
          aria-expanded={false}
          onClick={() => onOpen(true)}
          className="ml-auto text-xs font-semibold text-accent underline underline-offset-2 hover:text-ink"
        >
          {marked.length ? "Change" : "Choose"}
        </button>
      </div>
    );

  return (
    <div
      role="group"
      aria-labelledby="activity-box-ask"
      className="mb-2 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-2"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p id="activity-box-ask" className="text-sm font-semibold text-ink">
          Select the option(s) that best describe the activity you are assigning.
        </p>
        <button
          type="button"
          aria-expanded
          onClick={() => onOpen(false)}
          className="shrink-0 text-xs font-semibold text-pencil hover:text-ink"
        >
          {marked.length ? "Done" : "Hide"}
        </button>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {offered.map((a) => {
          const on = shown.includes(a.key);
          return (
            <button
              key={a.key}
              type="button"
              // A guess is the agent's, not a press: pressing it makes it the teacher's pick.
              aria-pressed={on && !guess}
              onClick={() => onPress(a.key)}
              className={`rounded-full border px-2 py-0 text-xs leading-5 ${
                on ? (guess ? GUESSED : PICKED) : UNPRESSED
              }`}
            >
              {a.label}
              {on && guess && <span className="font-semibold"> guess</span>}
            </button>
          );
        })}
      </div>
      {guess && marked.length > 0 && (
        <p className="mt-1.5 text-xs text-pencil">
          The agent worked this out from what you wrote. Press a heading to pick it yourself.
        </p>
      )}
      {waiting && (
        <p className="mt-1.5">
          <span className={BADGE}>sent with your message</span>
        </p>
      )}
    </div>
  );
}

/**
 * The activity box in the chat, under the agent's words. With no heading yet it offers the
 * headings to press. With one it shows it, marked "guess" when the agent worked it out, and
 * "Change" opens the headings. A press is the teacher's next message, sent at once. Only the
 * newest box in the chat is `live`: an older one still says what it said and cannot be pressed.
 */
export function ChatActivityBox({
  box,
  offered,
  live,
  busy,
  onPick,
}: {
  box: ChatActivity;
  offered: Activity[];
  live: boolean;
  busy: boolean;
  onPick: (key: string) => void;
}) {
  const [changing, setChanging] = useState(false);
  const has = box.headings ?? [];
  // In the lesson's own order: its heading first, then any a step has of its own.
  const marked = has.flatMap((key) => offered.filter((a) => a.key === key));
  // A question that is no longer the newest has been answered further down the chat.
  if (marked.length === 0 && !(box.ask && live)) return null;
  const choosing = live && (marked.length === 0 || changing);

  return (
    <div className="mt-2 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-1.5 text-sm text-ink">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">Activity</span>
        {marked.length === 0 && <span className="text-pencil">press the one that fits</span>}
        {marked.map((a) => (
          <span
            key={a.key}
            className={`rounded-full border px-2 py-0 text-xs leading-5 ${box.guess ? GUESSED : PICKED}`}
          >
            {a.label}
            {box.guess && <span className="font-semibold"> guess</span>}
          </span>
        ))}
        {live && marked.length > 0 && (
          <button
            type="button"
            aria-expanded={changing}
            onClick={() => setChanging(!changing)}
            className="text-xs font-semibold text-accent underline underline-offset-2 hover:text-ink"
          >
            {changing ? "Keep it" : "Change"}
          </button>
        )}
      </div>
      {choosing && (
        <div role="group" aria-label="Activity headings" className="mt-1.5 mb-1 flex flex-wrap gap-1">
          {offered
            // A heading the teacher pressed is not offered again. One the agent guessed is:
            // pressing it makes it the teacher's own.
            .filter((a) => box.guess || !has.includes(a.key))
            .map((a) => (
              <button
                key={a.key}
                type="button"
                disabled={busy}
                onClick={() => onPick(a.key)}
                className={`rounded-full border px-2 py-0 text-xs leading-5 disabled:opacity-60 ${UNPRESSED}`}
              >
                {a.label}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
