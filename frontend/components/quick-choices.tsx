"use client";

import { Fragment, useEffect, useRef } from "react";
import type { LessonCard } from "@/lib/api";
import { TutorFace } from "@/components/chat";

/**
 * The quick choices: the tutor's rules as things a teacher presses rather than writes. The
 * tutor line at the bottom of the typing box reads the rules back, and a tap on it opens the
 * settings under the box. Pressing choices composes a sentence the agent reads (and the server
 * takes literally), so every rule stays a variable in the prompt.
 */

/** The shape of the work: a right answer to work out, or open-ended writing judged against
 * criteria. Mirrors ActivityKind and ACTIVITY_PLAIN in the backend. A teacher is never asked
 * for it: the server takes it from the kind of activity. */
export type Activity = "answers" | "open";
export const ACTIVITY_PLAIN: Record<Activity, string> = {
  answers: "right answers",
  open: "open-ended writing",
};

/** The rule values the tutor line reads back, as the card's pills also see them. */
export type RuleValues = {
  hints: boolean;
  workedAfter: number;
};

/** What a lesson starts with. Mirrors the defaults of PolicyRules in
 * backend/app/agent/policy.py, which is the source of truth. */
export const DEFAULT_RULES: RuleValues = {
  hints: true,
  workedAfter: 1,
};

type RuleSource = Pick<LessonCard, "worked_step_after" | "hints_allowed">;

/** A lesson's rule values, from the same fields the card's pills are built from, so the tutor
 * line and the card can never disagree. */
export function ruleValuesFrom(source: RuleSource): RuleValues {
  return {
    hints: source.hints_allowed,
    workedAfter: source.worked_step_after,
  };
}

/** The groups, as the questions a teacher is asked; the tutor line points into these. */
export const GROUP = {
  hints: "Give hints towards the answer?",
  worked: "Show a worked step?",
  moving: "Can pupils move between parts?",
} as const;

export type Group = {
  /** The question the teacher sees. */
  name: string;
  /** How the sentence to the agent names this group, when it has no sentence of its own. */
  said?: string;
  options: string[];
};

/** Ready-made choices, so a teacher can shape the lesson by pressing rather than writing. The
 * sentences they compose (see `composeChoices`) are the ones the server also takes literally. */
export const CHOICES: Group[] = [
  // The tutor's rules first: these are what the tutor line points into.
  { name: GROUP.hints, options: ["Yes", "No"] },
  {
    name: GROUP.worked,
    options: ["Straight away", "After 1 wrong try", "After 2 wrong tries", "After 3 wrong tries"],
  },
  // Either way a pupil can leave a part for later and come back to it.
  { name: GROUP.moving, options: ["In order", "Freely"] },
  // Then how the lesson ends. The answer itself, the tutor's tone and who interrupts the
  // teacher are not offered here: a teacher who wants one says so in words, and the agent and
  // the server read those words as they read these.
  // Not "at the end": those words would read as the teacher asking to end a running lesson.
  { name: "At the end?", said: "Afterwards", options: ["Marks for each student", "A summary, no marks"] },
];

function tries(n: number): string {
  return n === 1 ? "after 1 wrong try" : `after ${n} wrong tries`;
}

function workedWords(n: number): string {
  return n === 0 ? "straight away" : tries(n);
}

/** One group's sentence, worded so the server's literal parser reads it the same way the
 * agent does. Null when the choice is the default and needs no sentence. */
function sentenceFor(group: Group, picked: string[]): string | null {
  const first = picked[0].toLowerCase();
  switch (group.name) {
    case GROUP.hints:
      return first === "no" ? "No hints towards answers." : "Hints towards the answer are fine.";
    case GROUP.worked:
      return `A worked step ${first}.`;
    case GROUP.moving:
      return first === "freely" ? "Pupils move freely between steps." : "Pupils move in order.";
    default:
      return `${group.said ?? group.name}: ${picked.join(", ")}.`;
  }
}

/** The sentence the picked choices make, for the agent to read. Empty when nothing is picked. */
export function composeChoices(picked: Record<string, string[]>): string {
  const parts = CHOICES.map((c) => (picked[c.name]?.length ? sentenceFor(c, picked[c.name]) : null)).filter(
    (s): s is string => Boolean(s),
  );
  return parts.length ? `Please use these choices for this lesson. ${parts.join(" ")}` : "";
}

export type Segment = { label?: string; text: string; group: string };

// A block of its own in the line: it moves to the next line whole, since a badge broken across
// two lines reads as two badges.
const BADGE =
  "inline-block max-w-full rounded-full bg-accent/10 px-2 py-0.5 text-xs font-normal leading-5 text-accent";

/** How many groups have a pick waiting to go with the next message. */
function chosenCount(picked: Record<string, string[]>): number {
  return CHOICES.filter((c) => picked[c.name]?.length).length;
}

/** The tutor's one-line read-back of the rules, as segments: the values a teacher most often
 * changes, each with the words in front of it and the group it opens. */
export function readBack(rules: RuleValues): Segment[] {
  return [
    { text: rules.hints ? "hints any time" : "no hints towards the answer", group: GROUP.hints },
    // With hints off there is no worked step either, as the card's pills say.
    { label: "worked step", text: rules.hints ? workedWords(rules.workedAfter) : "not at all", group: GROUP.worked },
  ];
}

/** The tutor line at the bottom of the typing box: the pencil, the rules in a few words, and
 * the values as buttons that open their question in the settings under the box. */
export function RuleReadBack({
  rules,
  subject,
  picked,
  open,
  active,
  onTap,
  onShowAll,
}: {
  rules: RuleValues;
  subject?: string;
  /** The picks waiting to be sent; counted here while the settings are closed. */
  picked: Record<string, string[]>;
  open: boolean;
  /** The group whose question the open settings were opened at. */
  active: string | null;
  onTap: (group: string) => void;
  onShowAll: () => void;
}) {
  const chosen = chosenCount(picked);
  return (
    <div className="flex items-start gap-2 leading-7 text-ink">
      <TutorFace subject={subject} />
      <p className="@container min-w-0 flex-1 [overflow-wrap:anywhere]">
        <span className="font-semibold">Tutor:</span>{" "}
        {readBack(rules).map((s) => {
          const on = open && active === s.group;
          return (
            <Fragment key={s.group}>
              {/* A value stays on the line of the words in front of it, so the line breaks
                  between rules, not inside one. Only where the longest rule fits: 14.75rem. */}
              <span className="@[14.75rem]:whitespace-nowrap">
                {s.label && `${s.label} `}
                <button
                  type="button"
                  aria-expanded={on}
                  onClick={() => onTap(s.group)}
                  className={`inline border-b-2 border-accent px-1 font-semibold ${
                    on
                      ? "rounded-[4px] bg-accent text-white"
                      : "rounded-t-[4px] bg-accent/10 text-ink hover:bg-accent/15"
                  }`}
                >
                  {s.text}
                </button>
              </span>
              {" · "}
            </Fragment>
          );
        })}
        <button
          type="button"
          aria-expanded={open}
          onClick={onShowAll}
          className="font-semibold text-accent underline underline-offset-2 hover:text-ink"
        >
          {open ? "hide settings" : "this lesson's settings"}
        </button>
        {!open && chosen > 0 && (
          <>
            {" "}
            <span className={BADGE}>{chosen} chosen, sent with your message</span>
          </>
        )}
      </p>
    </div>
  );
}

/** Toggles one option in a group: one pick per group, and pressing it again takes it back. */
export function togglePick(
  picked: Record<string, string[]>,
  name: string,
  option: string,
): Record<string, string[]> {
  const on = (picked[name] ?? []).includes(option);
  return { ...picked, [name]: on ? [] : [option] };
}

/** The tutor settings: what the tutor can do in this lesson, as questions with answers to
 * press. A sheet under the typing box, there only while it is open. Controlled by the page,
 * which keeps the picks, sends them hidden beside the teacher's next message, and decides
 * whether the panel is open. There is nothing to apply: pressing Send sends the words and the
 * picks together. */
export function QuickChoicesPanel({
  picked,
  onPick,
  open,
  onClose,
  focusGroup,
}: {
  picked: Record<string, string[]>;
  onPick: (name: string, option: string) => void;
  open: boolean;
  onClose: () => void;
  /** A group to bring into view and focus when the panel opens from the tutor line. */
  focusGroup: string | null;
}) {
  const groups = useRef<Record<string, HTMLDivElement | null>>({});
  const chosen = chosenCount(picked);

  useEffect(() => {
    if (!open || !focusGroup) return;
    const el = groups.current[focusGroup];
    if (!el) return;
    const frame = requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      el.querySelector<HTMLButtonElement>("button")?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [open, focusGroup]);

  if (!open) return null;
  return (
    <section
      aria-labelledby="tutor-settings-title"
      className="mt-2 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-3.5 py-2.5 shadow-sheet"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p id="tutor-settings-title" className="min-w-0 text-sm font-semibold text-ink">
          Tutor settings for this lesson{" "}
          <span className="font-normal text-pencil">(what the tutor can do in it)</span>
          {chosen > 0 && (
            <>
              {" "}
              <span className={BADGE}>{chosen} chosen, sent with your message</span>
            </>
          )}
        </p>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 text-xs font-semibold text-pencil hover:text-ink"
        >
          Done
        </button>
      </div>
      {/* One question per line, its answers beside it. The lines scroll inside a capped height,
          so beside a conversation the panel can never push the typing box, or the chat, off the
          screen. */}
      <div className="@container mt-1.5 max-h-[28dvh] space-y-0.5 overflow-y-auto border-t border-rule pt-1.5 pr-1">
        {CHOICES.map((c, i) => (
          <div
            key={c.name}
            role="group"
            aria-labelledby={`tutor-setting-${i}`}
            ref={(el) => {
              groups.current[c.name] = el;
            }}
            // The question the teacher tapped in the tutor line is marked, so they see where to press.
            className={`flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-[var(--radius-control)] px-1.5 py-1 ${
              c.name === focusGroup ? "bg-accent/10" : ""
            }`}
          >
            {/* The question sits beside its answers when the panel is wide (the blank screen),
                and above them in the narrow chat lane beside a card. */}
            <span id={`tutor-setting-${i}`} className="w-full text-xs font-semibold text-ink @md:w-48 @md:shrink-0">
              {c.name}
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-1">
              {c.options.map((o) => {
                const on = picked[c.name]?.includes(o) ?? false;
                return (
                  <button
                    key={o}
                    type="button"
                    aria-pressed={on}
                    onClick={() => onPick(c.name, o)}
                    className={`rounded-full border px-2 py-0 text-xs leading-5 ${
                      on ? "border-accent bg-accent text-white" : "border-rule-strong bg-sheet text-ink hover:border-ink"
                    }`}
                  >
                    {o}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
