"use client";

import { useEffect, useRef } from "react";
import type { LessonCard } from "@/lib/api";
import { TutorFace } from "@/components/chat";

/**
 * The quick choices: the tutor's rules as things a teacher presses rather than writes. They
 * sit under the typing box from the first screen on. Pressing choices composes a sentence the
 * agent reads (and the server takes literally), so every rule stays a variable in the prompt.
 */

/** The four depths of thinking in a teacher's words, 1 to 4. Mirrors DEPTH_PLAIN in
 * backend/app/agent/policy.py, which is the source of truth: the tutor is judged against the
 * fuller DOK words in brief.py, and these are their plain form, so a teacher's switch and the
 * tutor's judgment mean the same thing. */
export const DEPTH_PLAIN: Record<number, string> = {
  1: "recall it",
  2: "apply it or explain it",
  3: "justify it",
  4: "take it further",
};

/** The rule values a teacher most often changes, as the read-back row and the card's pills
 * both see them. */
export type RuleValues = {
  hints: boolean;
  workedAfter: number;
  answerAfter: number | null;
  depth: number;
  /** Who the tutor tells the teacher about at once, in plain words; the two it can never hold
   * back come first. */
  atOnce: string[];
};

/** What a lesson starts with. Mirrors the defaults of PolicyRules and ALWAYS_TOLD in
 * backend/app/agent/policy.py and alerts.py; those are the source of truth. */
export const DEFAULT_RULES: RuleValues = {
  hints: true,
  workedAfter: 1,
  answerAfter: null,
  depth: 2,
  atOnce: ["a wellbeing concern", "asking for the teacher"],
};

type RuleSource = Pick<
  LessonCard,
  "help" | "worked_step_after" | "hints_allowed" | "answer_after" | "depth"
>;

/** A lesson's rule values, from the same fields the card's pills are built from, so the row
 * under the box and the card can never disagree. */
export function ruleValuesFrom(source: RuleSource): RuleValues {
  return {
    hints: source.hints_allowed,
    workedAfter: source.worked_step_after,
    answerAfter: source.answer_after,
    depth: source.depth,
    // The same words and counts as the card's pills. The two signals never held back are in
    // this list already: the server lists them whatever the teacher set.
    atOnce: source.help.at_once.map(
      (a) => a.words.toLowerCase() + (a.after > 1 ? ` (after ${a.after} times)` : ""),
    ),
  };
}

/** The groups, as the questions a teacher is asked; the read-back row points into these. */
export const GROUP = {
  depth: "What kind of lesson?",
  hints: "Give hints towards the answer?",
  worked: "Show a worked step?",
  answer: "Give the answer itself?",
  atOnce: "Tell me straight away if a student",
} as const;

/** The depth options in the order of the depths, 1 to 4: a teacher picks the words, never a
 * number. */
export const DEPTH_OPTIONS = ["Recall the facts", "Apply or explain it", "Justify their answer", "Take it further"];

export type Group = {
  /** The question the teacher sees. */
  name: string;
  /** How the sentence to the agent names this group, when it has no sentence of its own. */
  said?: string;
  many?: boolean;
  options: string[];
};

/** Ready-made choices, so a teacher can shape the lesson by pressing rather than writing. The
 * sentences they compose (see `composeChoices`) are the ones the server also takes literally. */
export const CHOICES: Group[] = [
  // The tutor's rules first: these are what the read-back row points into.
  { name: GROUP.depth, options: DEPTH_OPTIONS },
  { name: GROUP.hints, options: ["Yes", "No"] },
  {
    name: GROUP.worked,
    options: ["Straight away", "After 1 wrong try", "After 2 wrong tries", "After 3 wrong tries"],
  },
  { name: GROUP.answer, options: ["Never", "After 2 wrong tries", "If they ask"] },
  {
    name: GROUP.atOnce,
    many: true,
    options: [
      "is struggling",
      "seems upset",
      "asks for me",
      "goes off task",
      "keeps asking for the answer",
      "has a misconception",
      "races ahead",
    ],
  },
  // Then the shape of the lesson.
  {
    name: "What should they do?",
    said: "Type of task",
    options: ["Practice questions", "Step-by-step explanation", "Problem solving", "Discussion", "Quick quiz"],
  },
  {
    name: "What kind of questions?",
    said: "Questions",
    options: ["Multiple choice", "Short answer", "Open-ended", "Show your working", "True or false"],
  },
  // Not "at the end": those words would read as the teacher asking to end a running lesson.
  { name: "At the end?", said: "Afterwards", options: ["Marks for each student", "A summary, no marks"] },
  {
    name: "How should the tutor sound?",
    said: "Tone",
    options: ["Warm and encouraging", "Calm and neutral", "Formal", "Playful"],
  },
];

/** "a, b and c", for the middle of a sentence. */
export function andList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function tries(n: number): string {
  return n === 1 ? "after 1 wrong try" : `after ${n} wrong tries`;
}

function workedWords(n: number): string {
  return n === 0 ? "straight away" : tries(n);
}

function answerWords(n: number | null): string {
  return n === null ? "never" : n === 0 ? "if they ask" : tries(n);
}

/** One group's sentence, worded so the server's literal parser reads it the same way the
 * agent does. Null when the choice is the default and needs no sentence. */
function sentenceFor(group: Group, picked: string[]): string | null {
  const first = picked[0].toLowerCase();
  switch (group.name) {
    case GROUP.depth: {
      const n = DEPTH_OPTIONS.indexOf(picked[0]) + 1;
      return `Teach to depth ${n}: students should ${DEPTH_PLAIN[n]}.`;
    }
    case GROUP.hints:
      return first === "no" ? "No hints towards answers." : "Hints towards the answer are fine.";
    case GROUP.worked:
      return `A worked step ${first}.`;
    case GROUP.answer:
      return first === "never" ? "The answer itself: never." : `The answer ${first}.`;
    case GROUP.atOnce:
      return `Tell me straight away when a student ${andList(picked)}.`;
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

export type Segment = { text: string; group?: string };

/** The tutor's one-line read-back of the rules, as segments: the values a teacher most often
 * changes carry the group they open. */
export function readBack(rules: RuleValues, hasLesson: boolean): Segment[] {
  return [
    { text: hasLesson ? "For this lesson I'll give " : "Unless you say otherwise, I'll give " },
    { text: rules.hints ? "hints any time" : "no hints towards the answer", group: GROUP.hints },
    { text: ", a worked step " },
    // With hints off there is no worked step either, as the card's pills say.
    { text: rules.hints ? workedWords(rules.workedAfter) : "not at all", group: GROUP.worked },
    { text: ", the answer " },
    { text: answerWords(rules.answerAfter), group: GROUP.answer },
    { text: ", and expect them to " },
    { text: DEPTH_PLAIN[rules.depth] ?? `work at depth ${rules.depth}`, group: GROUP.depth },
    { text: ". I'll tell you at once about " },
    // An older api can send an empty list; say so rather than trail off.
    { text: andList(rules.atOnce) || "nothing; it all goes in the record", group: GROUP.atOnce },
    { text: "." },
  ];
}

/** The read-back row: the pencil, the sentence, and the values as buttons that open their group. */
export function RuleReadBack({
  rules,
  hasLesson,
  subject,
  open,
  onTap,
  onShowAll,
}: {
  rules: RuleValues;
  hasLesson: boolean;
  subject?: string;
  open: boolean;
  onTap: (group: string) => void;
  onShowAll: () => void;
}) {
  const segments = readBack(rules, hasLesson);
  return (
    <div className="mt-3 flex items-start gap-2.5 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-3.5 py-2.5 text-sm leading-7 text-ink">
      <span className="mt-1.5">
        <TutorFace subject={subject} />
      </span>
      <p className="min-w-0 [overflow-wrap:anywhere]">
        {segments.map((s, i) =>
          s.group ? (
            <button
              key={i}
              type="button"
              onClick={() => onTap(s.group!)}
              className="inline rounded-t-[4px] border-b-2 border-progress bg-progress-wash px-1 font-semibold text-ink hover:bg-progress/15"
            >
              {s.text}
            </button>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
        {!hasLesson && (
          <>
            {" "}
            Tap any of those to change it, or{" "}
            <button
              type="button"
              aria-expanded={open}
              onClick={onShowAll}
              className="font-semibold text-progress underline underline-offset-2 hover:text-ink"
            >
              see all the tutor settings
            </button>
            .
          </>
        )}
      </p>
    </div>
  );
}

/** Toggles one option in a group: single pick by default, any number when the group says so. */
export function togglePick(
  picked: Record<string, string[]>,
  name: string,
  option: string,
  many?: boolean,
): Record<string, string[]> {
  const had = picked[name] ?? [];
  const on = had.includes(option);
  const next = many ? (on ? had.filter((o) => o !== option) : [...had, option]) : on ? [] : [option];
  return { ...picked, [name]: next };
}

/** The tutor settings: what the tutor can do in this lesson, as questions with answers to
 * press. Controlled by the page, which keeps the picks, sends them hidden beside the teacher's
 * next message, and decides whether the panel is open. There is nothing to apply: pressing
 * Send sends the words and the picks together. */
export function QuickChoicesPanel({
  picked,
  onPick,
  open,
  onToggle,
  focusGroup,
}: {
  picked: Record<string, string[]>;
  onPick: (name: string, option: string, many?: boolean) => void;
  open: boolean;
  onToggle: () => void;
  /** A group to bring into view and focus when the panel opens from the read-back row. */
  focusGroup: string | null;
}) {
  const groups = useRef<Record<string, HTMLDivElement | null>>({});
  const chosen = CHOICES.filter((c) => picked[c.name]?.length);

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

  return (
    <div className="mt-2 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 text-left text-sm font-semibold text-ink"
      >
        <span>
          Tutor settings{" "}
          <span className="font-normal text-pencil">(what it can do in this lesson)</span>
          {chosen.length > 0 && (
            <span className="ml-2 rounded-full bg-progress-wash px-2 py-0.5 text-xs font-normal text-progress">
              {chosen.length} chosen, sent with your message
            </span>
          )}
        </span>
        <span className="text-xs font-semibold text-pencil">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        /* One question per line, its answers beside it. The lines scroll inside a capped
           height, so beside a conversation the panel can never push its own button, or the
           chat, off the screen. */
        <div className="@container mt-1.5 max-h-[28dvh] space-y-1.5 overflow-y-auto border-t border-rule pt-1.5 pr-1">
          {CHOICES.map((c, i) => (
            <div
              key={c.name}
              role="group"
              aria-labelledby={`tutor-setting-${i}`}
              ref={(el) => {
                groups.current[c.name] = el;
              }}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
            >
              {/* The question sits beside its answers when the panel is wide (the blank screen),
                  and above them in the narrow chat lane beside a card. */}
              <span id={`tutor-setting-${i}`} className="w-full text-xs font-semibold text-ink @md:w-48 @md:shrink-0">
                {c.name}
                {c.many && <span className="font-normal text-pencil"> (any)</span>}
              </span>
              <div className="flex min-w-0 flex-1 flex-wrap gap-1">
                {c.options.map((o) => {
                  const on = picked[c.name]?.includes(o) ?? false;
                  return (
                    <button
                      key={o}
                      type="button"
                      aria-pressed={on}
                      onClick={() => onPick(c.name, o, c.many)}
                      className={`rounded-full border px-2 py-0 text-xs leading-5 ${
                        on ? "border-ink bg-ink text-white" : "border-rule-strong bg-sheet text-ink hover:border-ink"
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
      )}
    </div>
  );
}
