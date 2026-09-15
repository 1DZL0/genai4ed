"use client";

import { useSyncExternalStore, type ReactNode } from "react";

/* ---------- Actions ---------- */

export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "quiet" | "red" | "plain";
  size?: "sm" | "md";
}) {
  const look = {
    primary: "bg-ink text-white hover:bg-ink-hover disabled:bg-faint",
    quiet:
      "bg-sheet text-ink border border-rule-strong hover:border-ink disabled:text-faint disabled:hover:border-rule-strong",
    red: "bg-sheet text-red-pen border border-red-pen/50 hover:border-red-pen hover:bg-red-pen-wash",
    plain: "text-pencil underline underline-offset-4 decoration-rule-strong hover:text-ink hover:decoration-ink",
  }[variant];
  const scale =
    variant === "plain"
      ? size === "sm"
        ? "text-xs"
        : "text-sm"
      : size === "sm"
        ? "h-8 px-3 text-xs"
        : "h-10 px-4 text-sm";

  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)]
                  font-semibold whitespace-nowrap transition-colors disabled:cursor-not-allowed
                  ${scale} ${look} ${className}`}
    >
      {children}
    </button>
  );
}

/* ---------- Surfaces ---------- */

/** A sheet of paper on the desk. The title is a plain sentence-case heading. */
export function Panel({
  title,
  children,
  aside,
  description,
  flush = false,
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
  description?: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3">
        <div>
          <h2 className="text-base font-bold text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-pencil">{description}</p>}
        </div>
        {aside}
      </header>
      <div className={flush ? "" : "px-5 pb-5"}>{children}</div>
    </section>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div role="status" className="flex flex-col items-start gap-3 py-6 text-sm text-pencil">
      <p>{children}</p>
      {action}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-[var(--radius-control)] border border-red-pen/30 bg-red-pen-wash px-3 py-2 text-sm text-ink"
    >
      {children}
    </p>
  );
}

export function Notice({
  tone = "pencil",
  children,
}: {
  tone?: "pencil" | "amber" | "tick" | "red";
  children: ReactNode;
}) {
  const look = {
    pencil: "border-rule bg-sunken",
    amber: "border-amber/25 bg-amber-wash",
    tick: "border-tick/25 bg-tick-wash",
    red: "border-red-pen/30 bg-red-pen-wash",
  }[tone];
  return (
    <div
      role="status"
      className={`rounded-[var(--radius-control)] border px-4 py-3 text-sm text-ink ${look}`}
    >
      {children}
    </div>
  );
}

export function Skeleton({ rows = 3, label }: { rows?: number; label: string }) {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-12 animate-pulse rounded-[var(--radius-control)] bg-sunken"
          style={{ opacity: 1 - i * 0.18 }}
        />
      ))}
    </div>
  );
}

/* ---------- Subjects: exercise-book covers ---------- */

const COVERS: [RegExp, string, string][] = [
  [/math|algebra|geometr|arithm|statist/i, "var(--cover-maths)", "Maths"],
  [/scien|physic|chemi|biolog/i, "var(--cover-science)", "Science"],
  [/english|literat|writing|reading/i, "var(--cover-english)", "English"],
  [/histor|civic|religi|social/i, "var(--cover-humanities)", "History"],
  [/geograph|environment/i, "var(--cover-geography)", "Geography"],
  [/greek|french|spanish|german|language|latin/i, "var(--cover-languages)", "Languages"],
  [/art|music|drama|design/i, "var(--cover-arts)", "Arts"],
];

export function subjectCover(subject: string): { colour: string; name: string } {
  const hit = COVERS.find(([pattern]) => pattern.test(subject));
  const name = subject ? subject.charAt(0).toUpperCase() + subject.slice(1) : "General";
  return hit ? { colour: hit[1], name: hit[2] } : { colour: "var(--cover-other)", name };
}

export function SubjectName({ subject }: { subject: string }) {
  const { colour, name } = subjectCover(subject);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-pencil">
      <span aria-hidden className="size-2 rounded-full" style={{ background: colour }} />
      {name}
    </span>
  );
}

/* ---------- Marks ---------- */

export function Tick({ animate = false, className = "size-5" }: { animate?: boolean; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={`${animate ? "tick-draw" : ""} ${className}`}
      fill="none"
      stroke="var(--tick)"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4.5 12.5l5 5L19.5 6.5" pathLength={1} />
    </svg>
  );
}

/* ---------- The teacher's queue ---------- */

export const QUEUE_WORDS: Record<string, string> = {
  safeguarding: "Wellbeing concern",
  teacher_requested: "Asked for you",
  struggling: "Struggling",
  manipulation: "Trying to get round the rules",
  misconception_pattern: "Shared misconception",
  unresolved_question: "Unresolved question",
  off_task: "Off task",
  fast_progress: "Moving very fast",
};

export function QueueKind({ kind, priority }: { kind: string; priority: number }) {
  const look = priority <= 1 ? "text-red-pen" : priority === 2 ? "text-amber" : "text-pencil";
  return (
    <span className={`text-xs font-bold ${look}`}>{QUEUE_WORDS[kind] ?? kind.replace(/_/g, " ")}</span>
  );
}

/* ---------- Time ---------- */

/** 24-hour school time: "14:05". Never wraps, and matches the timetable. */
export function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

// One shared clock for every countdown on the page. The snapshot must be a
// stable value between ticks, so it is stored rather than read from Date.now().
let clockNow = 0;
function subscribeClock(onChange: () => void) {
  const id = window.setInterval(() => {
    clockNow = Date.now();
    onChange();
  }, 15_000);
  return () => window.clearInterval(id);
}
function clockSnapshot() {
  if (clockNow === 0) clockNow = Date.now();
  return clockNow;
}

/** Minutes until `iso`, refreshed every 15 seconds. `null` during server render. */
export function useMinutesLeft(iso: string | undefined): number | null {
  const now = useSyncExternalStore(subscribeClock, clockSnapshot, () => 0);
  if (!iso || now === 0) return null;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 60_000));
}

export function TimeLeft({ closesAt, status }: { closesAt: string | null; status: string }) {
  const minutes = useMinutesLeft(closesAt ?? undefined);
  if (status === "closed") return <span className="text-pencil">Ended</span>;
  if (!closesAt) return <span className="text-pencil">Not started</span>;
  if (minutes === null) return <span className="text-pencil">Ends at {clockTime(closesAt)}</span>;
  return (
    <span className="figures text-pencil" title={`Ends at ${clockTime(closesAt)}`}>
      {minutes === 0 ? "Ending now" : `${minutes} min left`}
    </span>
  );
}
