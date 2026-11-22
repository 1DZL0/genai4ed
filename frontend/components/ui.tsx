"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";

/* ---------- Actions ---------- */

export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  /** "pill": a rounded button for the things a card lets you do, so they read as buttons
   * rather than as text. "plain" is kept for small edits like Change. */
  variant?: "primary" | "quiet" | "red" | "plain" | "pill" | "pillDark";
  size?: "sm" | "md";
  ref?: React.Ref<HTMLButtonElement>;
}) {
  const look = {
    primary: "bg-accent text-white hover:bg-accent-hover disabled:bg-faint",
    quiet:
      "bg-sheet text-ink border border-rule-strong hover:border-ink disabled:text-faint disabled:hover:border-rule-strong",
    red: "bg-sheet text-red-pen border border-red-pen/50 hover:border-red-pen hover:bg-red-pen-wash",
    plain: "text-pencil underline underline-offset-4 decoration-rule-strong hover:text-ink hover:decoration-ink",
    pill: "bg-sheet text-ink border border-rule-strong hover:border-ink hover:bg-sunken disabled:text-faint disabled:hover:border-rule-strong",
    pillDark: "bg-accent text-white hover:bg-accent-hover disabled:bg-faint",
  }[variant];
  const round = variant === "pill" || variant === "pillDark";
  const scale =
    variant === "plain"
      ? size === "sm"
        ? "text-xs"
        : "text-sm"
      : round
        ? size === "sm"
          ? "h-8 px-3.5 text-sm"
          : "h-10 px-4 text-sm"
        : size === "sm"
          ? "h-8 px-3 text-xs"
          : "h-10 px-4 text-sm";
  const shape = round ? "rounded-full" : "rounded-[var(--radius-control)]";

  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 ${shape}
                  font-semibold whitespace-nowrap transition-colors disabled:cursor-not-allowed
                  ${scale} ${look} ${className}`}
    >
      {children}
    </button>
  );
}

/* ---------- Surfaces ---------- */

/** A sheet of paper on the desk; the title is a plain sentence-case heading. */
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
    <section className="rounded-[var(--radius-sheet)] border border-rule bg-sheet shadow-sheet">
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

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="flex flex-col items-start gap-3 py-6 text-sm text-pencil">
      <p>{children}</p>
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
  tone?: "pencil" | "amber" | "tick";
  children: ReactNode;
}) {
  const look = {
    pencil: "border-rule bg-sunken",
    amber: "border-amber/25 bg-amber-wash",
    tick: "border-tick/25 bg-tick-wash",
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

export function Tick({ className }: { className: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={className}
      fill="none"
      stroke="var(--tick)"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4.5 12.5l5 5L19.5 6.5" />
    </svg>
  );
}

/* ---------- The teacher's queue ---------- */

export const QUEUE_WORDS: Record<string, string> = {
  safeguarding: "Wellbeing concern",
  teacher_requested: "Asked for you",
  struggling: "Struggling",
  manipulation: "Trying to get the answer (possible cheating)",
  policy_conflict: "Agent reply held back",
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

/** 24-hour school time: "14:05". */
export function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

// One shared clock for every countdown; the snapshot is stored so it stays stable between ticks.
let clockNow = 0;
function subscribeClock(onChange: () => void) {
  // A countdown that has just appeared reads the time now, not up to 15 seconds ago: a
  // 20-minute lesson started a moment ago showed "21 min left".
  if (Date.now() - clockNow > 1_000) {
    clockNow = Date.now();
    onChange();
  }
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
function useMinutesLeft(iso: string | undefined): number | null {
  const now = useSyncExternalStore(subscribeClock, clockSnapshot, () => 0);
  if (!iso || now === 0) return null;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 60_000));
}

export function TimeLeft({ closesAt, status }: { closesAt: string | null; status: string }) {
  const minutes = useMinutesLeft(closesAt ?? undefined);
  if (status === "closed") return <span className="text-pencil">Ended</span>;
  if (!closesAt) return <span className="text-pencil">Not started</span>;
  if (minutes === null) return <span className="text-pencil">Ends at {clockTime(closesAt)}</span>;
  // Hours away (a lesson kept open, as for a demo): the day and time, not thousands of minutes.
  if (minutes > 120) {
    const day = new Date(closesAt).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    return (
      <span className="figures text-pencil">
        Ends {day} {clockTime(closesAt)}
      </span>
    );
  }
  // The last five minutes turn amber and the end red, so the clock is seen before it acts.
  const tone =
    minutes === 0
      ? "font-semibold text-red-pen"
      : minutes <= 5
        ? "font-semibold text-amber"
        : "text-pencil";
  return (
    <span className={`figures ${tone}`} title={`Ends at ${clockTime(closesAt)}`}>
      {minutes === 0 ? "Ending now" : `${minutes} min left`}
    </span>
  );
}

/* ---------- the reader's text size ---------- */

const SIZES = ["normal", "large", "larger"] as const;
type Size = (typeof SIZES)[number];
const SIZE_KEY = "pact-text-size";

// A small store outside React: the chosen size, read once from this browser and applied to
// the root element, so every page and every tab agrees without a flash of setState.
let sizeNow: Size | null = null;
const sizeListeners = new Set<() => void>();

function applySize(size: Size) {
  document.documentElement.setAttribute("data-size", size === "normal" ? "" : size);
}
function loadSize(): Size {
  if (sizeNow) return sizeNow;
  let saved = "normal";
  try {
    saved = window.localStorage.getItem(SIZE_KEY) ?? "normal";
  } catch {
    /* a private window: normal */
  }
  sizeNow = (SIZES as readonly string[]).includes(saved) ? (saved as Size) : "normal";
  applySize(sizeNow);
  return sizeNow;
}
function subscribeSize(onChange: () => void) {
  sizeListeners.add(onChange);
  loadSize();
  return () => {
    sizeListeners.delete(onChange);
  };
}
function chooseSize(next: Size) {
  sizeNow = next;
  applySize(next);
  try {
    window.localStorage.setItem(SIZE_KEY, next);
  } catch {
    /* a private window: the choice lasts the page */
  }
  sizeListeners.forEach((fn) => fn());
}

/** Three sizes of text for the whole page, remembered in this browser. Everything in rem
 * follows, so the boxes grow with the words. */
export function TextSize({ className = "" }: { className?: string }) {
  const size = useSyncExternalStore(subscribeSize, loadSize, () => "normal" as Size);
  return (
    <span
      role="group"
      aria-label="Text size"
      className={`inline-flex items-baseline overflow-hidden rounded-full border border-rule-strong bg-sheet ${className}`}
    >
      {SIZES.map((s, i) => (
        <button
          key={s}
          type="button"
          aria-pressed={size === s}
          aria-label={`${s === "normal" ? "Normal" : s === "large" ? "Large" : "Larger"} text`}
          onClick={() => chooseSize(s)}
          className={`px-2.5 font-serif font-semibold leading-none text-ink hover:bg-sunken ${
            size === s ? "bg-accent text-white hover:bg-accent" : ""
          } ${i === 0 ? "py-1.5 text-[13px]" : i === 1 ? "py-1 text-[16px]" : "py-0.5 text-[19px]"}`}
        >
          A
        </button>
      ))}
    </span>
  );
}

/* ---------- the lesson clock ---------- */

/** The shared clock, ticking every 15 seconds; 0 during server render. */
export function useClockNow(): number {
  return useSyncExternalStore(subscribeClock, clockSnapshot, () => 0);
}

/** Whole minutes from `now` until `iso`, never below 0; null with no deadline or no clock. */
export function minutesUntil(iso: string | null | undefined, now: number): number | null {
  if (!iso || now === 0) return null;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 60_000));
}

function ClockGlyph({ className = "size-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className={`${className} fill-none stroke-current`} strokeWidth={1.8} strokeLinecap="round">
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4.2l2.6 1.6" />
    </svg>
  );
}

/** The tone of a countdown: quiet, then amber for the last five minutes, then red at zero. */
export function clockTone(minutes: number | null): "quiet" | "amber" | "red" {
  if (minutes === null) return "quiet";
  if (minutes === 0) return "red";
  return minutes <= 5 ? "amber" : "quiet";
}

/** The pupil's clock: a small tablet in the corner with the minutes left, amber for the last
 * five, red and "Time's up" at zero. Paused and ended say so instead. */
export function TimerBadge({ closesAt, status, className = "" }: { closesAt: string | null; status: string; className?: string }) {
  const minutes = minutesUntil(closesAt, useClockNow());
  const tone = clockTone(minutes);
  const look =
    status === "closed"
      ? "border-rule bg-sunken text-pencil"
      : status === "paused"
        ? "border-amber/60 bg-amber-wash text-amber"
        : tone === "red"
          ? "border-red-pen/60 bg-red-pen-wash text-red-pen"
          : tone === "amber"
            ? "border-amber/60 bg-amber-wash text-amber"
            : "border-rule-strong bg-sheet text-ink";
  const words =
    status === "closed"
      ? "Ended"
      : status === "paused"
        ? "Paused"
        : !closesAt
          ? "Not started"
          : minutes === null
            ? `Ends ${clockTime(closesAt)}`
            : minutes === 0
              ? "Time's up"
              : minutes > 120
                ? `Ends ${clockTime(closesAt)}`
                : `${minutes} min`;
  return (
    <span
      role="timer"
      aria-live="off"
      aria-label={status === "open" && minutes !== null ? `${minutes} minutes left` : words}
      title={closesAt ? `Ends at ${clockTime(closesAt)}` : undefined}
      className={`figures inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm font-bold shadow-[inset_0_1px_0_rgb(255_255_255/0.6)] ${look} ${className}`}
    >
      <ClockGlyph />
      {words}
    </span>
  );
}

/** The teacher's clock: the time left as a button with a plus segment on its end. Pressing
 * the plus opens a box to type minutes to add. */
export function TimerControl({
  closesAt,
  status,
  busy,
  onAdd,
}: {
  closesAt: string | null;
  status: string;
  busy: boolean;
  onAdd: (minutes: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState("10");
  const left = minutesUntil(closesAt, useClockNow());
  const tone = clockTone(left);
  const running = status === "open" || status === "paused";
  const look =
    tone === "red" && status === "open"
      ? "border-red-pen bg-red-pen-wash text-red-pen"
      : tone === "amber" && status === "open"
        ? "border-amber bg-amber-wash text-amber"
        : "border-rule-strong bg-sheet text-ink";
  const words =
    status === "closed"
      ? "Ended"
      : !closesAt
        ? "Not started"
        : left === null
          ? `Ends ${clockTime(closesAt)}`
          : left === 0
            ? "Time's up"
            : left > 120
              ? `Ends ${clockTime(closesAt)}`
              : `${left} min left`;
  const n = Math.max(1, Math.min(120, Math.round(Number(minutes) || 0)));
  function add() {
    onAdd(n);
    setOpen(false);
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className={`figures inline-flex items-stretch overflow-hidden rounded-lg border text-sm font-bold ${look}`}>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1" title={closesAt ? `Ends at ${clockTime(closesAt)}` : undefined}>
          <ClockGlyph />
          {words}
        </span>
        {running && closesAt && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            disabled={busy}
            aria-expanded={open}
            aria-label="Add minutes to the lesson"
            className="border-l border-current/30 px-2 text-base leading-none hover:bg-sunken disabled:opacity-50"
          >
            +
          </button>
        )}
      </span>
      {open && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
          className="inline-flex items-center gap-1.5 text-sm"
        >
          <label className="sr-only" htmlFor="add-minutes">
            Minutes to add
          </label>
          <input
            id="add-minutes"
            type="number"
            min={1}
            max={120}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
            autoFocus
            className="figures h-8 w-16 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
          />
          <span className="text-pencil">min</span>
          <Button size="sm" type="submit" disabled={busy}>
            Add
          </Button>
          <Button size="sm" variant="plain" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </form>
      )}
    </span>
  );
}
