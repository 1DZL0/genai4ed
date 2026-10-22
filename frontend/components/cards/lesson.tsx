"use client";

import { useId, useState } from "react";
import type { LessonCard } from "@/lib/api";
import { APPROACHES, APPROACH_WORKED_STEP, approachName } from "@/lib/approaches";
import { removeWords } from "@/components/cards/lesson-status";
import { ClassName, Row, Sheet, type Act } from "@/components/cards/parts";
import { Button, SubjectName, clockTime } from "@/components/ui";

/** A lesson as the teacher works on it: what it is, what they can do with it, and what the agent will teach. */

const LINK =
  "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink";

/** What each kind of step is, in a teacher's words. */
const KIND_WORDS: Record<string, string> = {
  explain: "the agent explains",
  question: "a question",
  practice: "practice",
  check: "a check",
};

/** What each depth of thinking asks of a student, 1 to 4, in a teacher's words. */
const DEPTH_WORDS: Record<number, string> = {
  1: "recall",
  2: "apply or explain",
  3: "justify or use evidence",
  4: "extended reasoning",
};

/** "a, b and c", for the middle of a sentence. */
function andList(items: string[]): string {
  return items.length <= 1
    ? items.join("")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** The steps the agent's own fill-ins point at, by number: "step 2 criteria" and "step 2" both
 * mean step 2. Names that are not about one step ("objectives", "rules") only go in the box. */
function stepsToCheck(names: string[]): Map<number, string[]> {
  const steps = new Map<number, string[]>();
  for (const name of names) {
    const hit = /^step\s+(\d+)\b/i.exec(name.trim());
    if (!hit) continue;
    const n = Number(hit[1]);
    steps.set(n, [...(steps.get(n) ?? []), name]);
  }
  return steps;
}

export function Lesson({
  card,
  act,
  busy,
  say,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  say?: (words: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [approachOpen, setApproachOpen] = useState(false);
  const approved = card.status === "active";

  return (
    <Sheet>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <SubjectName subject={card.subject} />
          <h2 className="font-serif text-xl leading-snug font-semibold text-ink">
            {card.title}
          </h2>
          <p className="text-sm text-pencil">
            {card.steps.length} steps, {card.duration_minutes} minutes
            {card.assessment.length > 0 &&
              ` · marked on ${card.assessment.map((c) => `${c.name} (${c.max})`).join(", ")}`}
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-sm font-semibold ${
            approved
              ? "bg-tick-wash text-tick"
              : card.status === "closed"
                ? "bg-sunken text-pencil"
                : "bg-amber-wash text-amber"
          }`}
        >
          {approved
            ? "Ready to teach"
            : card.status === "closed"
              ? "An earlier version"
              : card.approved_lesson_id
                ? "A change you haven't approved"
                : "Draft"}
        </span>
      </div>

      <ToCheck card={card} />
      <UnitRow card={card} act={act} busy={busy} />
      <ApproachRow
        card={card}
        act={act}
        busy={busy}
        open={approachOpen}
        onOpen={() => setApproachOpen(true)}
        onClose={() => setApproachOpen(false)}
      />
      <Stages card={card} />
      <WhatYouCanDo card={card} act={act} busy={busy} />
      <TaughtBefore card={card} act={act} busy={busy} />
      {say && !approved && !card.live && <QuickChoices say={say} busy={busy} />}
      <WhatItTeaches card={card} act={act} busy={busy} open={open} />
      <LessonFooter
        card={card}
        act={act}
        busy={busy}
        open={open}
        onToggle={() => setOpen(!open)}
        onApproach={card.approach ? undefined : () => setApproachOpen(true)}
      />
    </Sheet>
  );
}

/** "Today, 14:10" for a lesson taught today, otherwise the day: "19 Oct". */
function whenTaught(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString()
    ? `Today, ${clockTime(iso)}`
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** Every time this lesson was taught, newest first, each opening that run's summary and the
 * note on every student: what a teacher checks before teaching it again or marking on paper. */
function TaughtBefore({ card, act, busy }: { card: LessonCard; act: Act; busy: boolean }) {
  const [all, setAll] = useState(false);
  const past = card.runs.filter((r) => r.status === "closed");
  if (past.length === 0) return null;
  const shown = all ? past : past.slice(0, 3);
  return (
    <div className="mt-3">
      <p className="text-xs font-bold text-pencil">Taught before</p>
      <ul className="mt-1.5 divide-y divide-rule overflow-hidden rounded-[var(--radius-sheet)] border border-rule">
        {shown.map((r) => (
          <li key={r.session_id}>
            <button
              type="button"
              disabled={busy}
              onClick={() => act({ action: "show_outcomes", session_id: r.session_id })}
              className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm hover:bg-sunken disabled:opacity-60"
            >
              <span className="figures shrink-0 text-pencil">{whenTaught(r.opened_at ?? r.closed_at)}</span>
              <ClassName label={r.class_label} className="font-semibold text-ink" />
              <span className="text-pencil">
                {r.took_part} of {r.students} took part, {r.finished} finished
              </span>
              {r.outcomes_to_confirm > 0 && (
                <span className="rounded-full bg-amber-wash px-2 py-0.5 text-xs font-semibold text-amber">
                  {r.outcomes_to_confirm} to confirm
                </span>
              )}
              {r.open_alerts > 0 && (
                <span className="rounded-full bg-red-pen-wash px-2 py-0.5 text-xs font-semibold text-red-pen">
                  {r.open_alerts} still open
                </span>
              )}
              <span className="ml-auto font-semibold text-ink underline decoration-rule-strong underline-offset-4">
                Summary
              </span>
            </button>
          </li>
        ))}
      </ul>
      {past.length > 3 && (
        <button type="button" onClick={() => setAll(!all)} className={`${LINK} mt-1.5 text-sm`}>
          {all ? "Show fewer" : `Show all ${past.length} times it was taught`}
        </button>
      )}
    </div>
  );
}

/** Which unit the lesson is part of, and a box to change that. A unit is only a name for now. */
function UnitRow({ card, act, busy }: { card: LessonCard; act: Act; busy: boolean }) {
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(card.unit ?? "");

  async function put(unit: string) {
    await act({ action: "set_unit", lesson_id: card.lesson_id, text: unit });
    setEditing(false);
  }

  const open = () => {
    setName(card.unit ?? "");
    setEditing(true);
  };
  // Units the teacher already has, to pick with one tap; the one it is in is left out.
  const others = card.units.filter((u) => u !== card.unit);

  if (!editing) {
    return card.unit ? (
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full bg-tick-wash px-3 py-1 text-tick">
          <span className="font-semibold">Unit:</span>
          <span className="font-semibold [overflow-wrap:anywhere]">{card.unit}</span>
        </span>
        <button type="button" disabled={busy} onClick={open} className={`${LINK} disabled:opacity-40`}>
          Change
        </button>
      </div>
    ) : (
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-[var(--radius-sheet)] bg-tick-wash px-3 py-2 text-sm">
        <span className="text-ink">Keep lessons on the same topic together in a unit.</span>
        <button
          type="button"
          disabled={busy}
          onClick={open}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-tick px-3.5 py-1 font-semibold text-white hover:opacity-90 disabled:opacity-40"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" className="size-3.5 fill-none stroke-current" strokeWidth={2.2}>
            <path d="M8 3v10M3 8h10" />
          </svg>
          {card.units.length > 0 ? "Add to a unit" : "Start a unit"}
        </button>
      </div>
    );
  }
  return (
    <form
      className="mt-2 flex flex-col gap-2 rounded-[var(--radius-sheet)] bg-tick-wash px-3 py-2.5 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        void put(name);
      }}
    >
      {others.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-ink">Add it to</span>
          {others.map((u) => (
            <button
              key={u}
              type="button"
              disabled={busy}
              onClick={() => void put(u)}
              className="max-w-full rounded-full border border-tick/40 bg-sheet px-3 py-0.5 font-semibold text-tick [overflow-wrap:anywhere] hover:border-tick disabled:opacity-40"
            >
              {u}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${id}-unit`} className="text-ink">
          {others.length > 0 ? "or a new unit" : "Name the unit"}
        </label>
        <input
          id={`${id}-unit`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={80}
          placeholder="Percentages"
          className="h-8 min-w-0 flex-1 rounded-full border border-rule-strong bg-sheet px-3 text-sm text-ink"
        />
        <Button size="sm" type="submit" disabled={busy || !name.trim() || name.trim() === (card.unit ?? "")}>
          Save
        </Button>
        {card.unit && (
          <Button size="sm" variant="plain" type="button" disabled={busy} onClick={() => void put("")}>
            Take it out
          </Button>
        )}
        <Button size="sm" variant="plain" type="button" onClick={() => setEditing(false)}>
          Not now
        </Button>
      </div>
    </form>
  );
}

/** The teaching approach a lesson is taught by, for a side-by-side comparison. Shown only once
 * set; until then it is reached from a small link in the footer. */
function ApproachRow({
  card,
  act,
  busy,
  open,
  onOpen,
  onClose,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const id = useId();
  const [pick, setPick] = useState(card.approach ?? "");
  if (!open && !card.approach) return null;

  async function save() {
    // The server sets the approach's rule on a new version; the agent is told the approach on
    // every turn, so nothing needs redrafting.
    await act({ action: "set_approach", lesson_id: card.lesson_id, text: pick });
    onClose();
  }
  // A rule changed by hand away from the approach's makes this lesson a poor comparison.
  const ruleChanged =
    card.approach != null &&
    card.approach in APPROACH_WORKED_STEP &&
    card.worked_step_after !== APPROACH_WORKED_STEP[card.approach];

  if (!open) {
    return (
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 rounded-[var(--radius-control)] bg-sunken px-3 py-1.5 text-sm">
        <span className="text-pencil">Taught by</span>
        <span className="font-semibold text-ink">{approachName(card.approach)}</span>
        {ruleChanged && (
          <span className="basis-full text-xs text-amber">
            The worked-step rule was changed from this approach&apos;s, so the comparison is not
            like for like.
          </span>
        )}
        <Button
          type="button"
          size="sm"
          variant="pill"
          disabled={busy}
          title="A copy with the same steps, questions and marks, taught the other way"
          onClick={() =>
            act({
              action: "copy_with_approach",
              lesson_id: card.lesson_id,
              text: card.approach === "direct" ? "inquiry" : "direct",
            })
          }
          className="ml-auto"
        >
          Make the other version
        </Button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setPick(card.approach ?? "");
            onOpen();
          }}
          className={`${LINK} disabled:opacity-40`}
        >
          Change
        </button>
      </div>
    );
  }
  return (
    <form
      className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] bg-sunken px-3 py-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label htmlFor={`${id}-approach`} className="text-pencil">
        Taught by
      </label>
      <select
        id={`${id}-approach`}
        value={pick}
        onChange={(e) => setPick(e.target.value)}
        className="h-8 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
      >
        <option value="">No set approach</option>
        {Object.entries(APPROACHES).map(([key, a]) => (
          <option key={key} value={key}>
            {a.name}
          </option>
        ))}
      </select>
      <Button size="sm" type="submit" disabled={busy || pick === (card.approach ?? "")}>
        Save
      </Button>
      <Button size="sm" variant="plain" type="button" onClick={onClose}>
        Not now
      </Button>
      <span className="basis-full text-xs text-pencil">
        The agent is told the approach while it drafts and on every turn with a student. For a
        comparison, make the other lesson from the same material with the other approach.
      </span>
    </form>
  );
}

/** Where the lesson is on its way to a class, and what that means right now. */
function Stages({ card }: { card: LessonCard }) {
  const approved = card.status === "active";
  const current = card.live ? 3 : approved ? 2 : 0;
  const names = ["Write it together", "Approve it", "Start it with a class"];
  const caption = card.status === "closed"
    ? "An earlier version of this lesson, kept for the record. The one you work on is in your list."
    : card.live
    ? `Running now with ${card.live.class_label}. Press the class to see how it's going.`
    : approved
      ? "Approved. Choose a class below and start it when the class is ready."
      : card.approved_lesson_id
        ? "You changed it. Approve the change, or students keep getting the approved version."
        : card.missing.length > 0
          ? "The agent fills this in as you talk. Students see nothing until you approve it."
          : "Everything it needs is here. Approve it when it says what you want.";

  return (
    <div className="mt-3">
      <ol
        className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs"
        aria-label="Where this lesson is"
      >
        {names.map((name, i) => {
          const done = i < current;
          const now = i === current;
          return (
            <li key={name} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={`figures flex size-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                  done
                    ? "bg-tick-wash text-tick"
                    : now
                      ? "bg-ink text-white"
                      : "border border-rule-strong text-pencil"
                }`}
              >
                {done ? "\u2713" : i + 1}
              </span>
              <span
                className={
                  now
                    ? "font-semibold text-ink"
                    : done
                      ? "text-ink"
                      : "text-pencil"
                }
              >
                {name}
                {now && <span className="sr-only"> (now)</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-1.5 text-sm text-pencil">{caption}</p>
    </div>
  );
}

/** What the agent filled in itself rather than from the teacher's words, shown on a draft until
 * approving confirms it all. */
function ToCheck({ card }: { card: LessonCard }) {
  if (card.status !== "draft" || card.to_check.length === 0) return null;
  return (
    <p className="mt-3 rounded-[var(--radius-control)] bg-amber-wash px-3 py-2 text-sm text-ink">
      <span className="font-semibold text-amber">
        The agent wrote these itself, check them before you approve:
      </span>{" "}
      {card.to_check.join(", ")}.
    </p>
  );
}

/** A step's depth as a small label, muted when nobody set it and it is the usual 2. */
function DepthLabel({ depth, set }: { depth: number; set: boolean }) {
  const words = DEPTH_WORDS[depth];
  return (
    <span
      title={set ? "Set for this step" : "Nobody set it, so it is the usual depth 2"}
      className={`rounded-full bg-sunken px-2 py-0.5 text-xs ${
        set ? "font-semibold text-ink" : "text-pencil"
      }`}
    >
      {words ? `depth ${depth}, ${words}` : `depth ${depth}`}
    </span>
  );
}

/** The lesson in four lines, read back before the teacher approves it: the steps and their
 * depths, the help rules, what interrupts them at once, and the marks. */
function Decided({ card }: { card: LessonCard }) {
  const n = card.steps.length;
  const depths = card.steps.map((s) => s.depth).join(", ");
  const atOnce = card.rules_in_words.find((r) => r.startsWith("The agent tells you at once"));
  const rules = card.rules_in_words.filter((r) => r !== atOnce).join(" ");
  const marks =
    card.assessment.length > 0
      ? `Marked on ${card.assessment.map((c) => `${c.name} (${c.max})`).join(", ")}.`
      : "Not marked: a summary and a note on each student.";
  return (
    <div className="mb-2 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-2 text-sm">
      <p className="text-xs font-bold text-pencil">What you decided</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink">
        <li>
          {n === 1 ? "1 step, with a finish line" : `${n} steps, each with a finish line`}, depth{" "}
          {depths}.
        </li>
        {rules && <li>{rules}</li>}
        <li>{atOnce ?? "Nothing interrupts you at once; it all goes in the record to read later."}</li>
        <li>{marks}</li>
      </ul>
    </div>
  );
}

/** Approving it, and running it with a class. Above the detail, not under it. */
function WhatYouCanDo({
  card,
  act,
  busy,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
}) {
  const id = useId();
  // One class: it is already chosen, so starting is one press.
  const [klass, setKlass] = useState(card.classes.length === 1 ? card.classes[0].id : "");
  // Said once under the buttons, until the teacher has tried a preview.
  const [previewed, setPreviewed] = useState(false);
  const chosen = card.classes.find((c) => c.id === klass);
  const ready = card.missing.length === 0;
  const approved = card.status === "active";
  const draft = card.status === "draft";
  const canPreview = draft && card.steps.length > 0;

  return (
    <div className="mt-3 border-y border-rule py-2.5">
      {draft && ready && <Decided card={card} />}
      <div className="flex flex-wrap items-center gap-2">
        {draft && (
          <Button
            disabled={busy || !ready}
            onClick={() => act({ action: "approve", lesson_id: card.lesson_id })}
          >
            Approve
          </Button>
        )}
        {canPreview && (
          <Button
            size="sm"
            variant="pill"
            disabled={busy}
            title="How step 1 would open for a student, written into the chat. Nothing reaches a student."
            onClick={() => {
              setPreviewed(true);
              void act({ action: "preview_lesson", lesson_id: card.lesson_id });
            }}
          >
            Preview as a student
          </Button>
        )}
        {(approved || card.approved_lesson_id) && (
          <>
            <label className="sr-only" htmlFor={`${id}-class`}>
              Class to teach
            </label>
            <select
              id={`${id}-class`}
              value={klass}
              onChange={(e) => setKlass(e.target.value)}
              className="h-10 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-base text-ink"
            >
              <option value="">Choose a class</option>
              {card.classes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} ({c.students})
                </option>
              ))}
            </select>
            <Button
              disabled={busy || !klass}
              onClick={() =>
                act({ action: "run", lesson_id: card.lesson_id, class_id: klass })
              }
            >
              {chosen ? `Start with ${chosen.label}` : "Start the lesson"}
            </Button>
            {!klass && (
              <span className="text-xs text-pencil">
                {card.classes.length === 0 ? (
                  <a
                    href="/teacher/classes"
                    className="inline-flex h-8 items-center rounded-full border border-rule-strong bg-sheet px-3.5 text-sm font-semibold text-ink hover:border-ink"
                  >
                    Make a class first
                  </a>
                ) : (
                  "Choose the class, then press Start."
                )}
              </span>
            )}
          </>
        )}
        {card.live && (
          <Button
            size="sm"
            variant="quiet"
            disabled={busy}
            onClick={() =>
              act({ action: "show_class", session_id: card.live!.session_id })
            }
          >
            Running with {card.live.class_label}
          </Button>
        )}
        {/* What to do next, said once, where the buttons are. */}
        {!ready && (
          <span className="text-xs text-amber">
            To approve it, it still needs {andList(card.missing)}. Say it in the
            chat and the agent adds it.
          </span>
        )}
        {canPreview && !previewed && (
          <span className="basis-full text-xs text-pencil">
            Preview as a student is one model call; nothing reaches a student.
          </span>
        )}
      </div>
    </div>
  );
}

/** Ready-made choices, so a teacher can shape the lesson by pressing rather than writing. */
const CHOICES: { name: string; many?: boolean; options: string[] }[] = [
  {
    name: "Type of task",
    options: ["Practice questions", "Step-by-step explanation", "Problem solving", "Discussion", "Quick quiz"],
  },
  {
    name: "Questions",
    options: ["Multiple choice", "Short answer", "Open-ended", "Show your working", "True or false"],
  },
  {
    name: "Level",
    options: ["Remember the facts", "Understand why", "Use it in a new problem", "Analyse and judge"],
  },
  {
    name: "Help while working",
    options: [
      "Hints only",
      "A worked step after one wrong try",
      "The answer after two wrong tries",
      "Never give the answer",
    ],
  },
  { name: "At the end", options: ["Marks for each student", "A summary, no marks"] },
  { name: "Tone", options: ["Warm and encouraging", "Calm and neutral", "Formal", "Playful"] },
  {
    name: "Tell me straight away when a student",
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
];

function QuickChoices({ say, busy }: { say: (words: string) => void; busy: boolean }) {
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const chosen = CHOICES.filter((c) => picked[c.name]?.length);

  function toggle(name: string, option: string, many?: boolean) {
    setPicked((now) => {
      const had = now[name] ?? [];
      const on = had.includes(option);
      const next = many ? (on ? had.filter((o) => o !== option) : [...had, option]) : on ? [] : [option];
      return { ...now, [name]: next };
    });
  }

  return (
    <details className="group mt-3 rounded-[var(--radius-control)] border border-rule bg-sunken px-3 py-2">
      <summary className="cursor-pointer text-sm font-semibold text-ink">
        Quick choices <span className="font-normal text-pencil">(press instead of typing)</span>
      </summary>
      <div className="mt-2 space-y-3">
        {CHOICES.map((c) => (
          <fieldset key={c.name}>
            <legend className="text-xs font-bold text-pencil">
              {c.name}
              {c.many && " (pick any)"}
            </legend>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {c.options.map((o) => {
                const on = picked[c.name]?.includes(o) ?? false;
                return (
                  <button
                    key={o}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggle(c.name, o, c.many)}
                    className={`rounded-full border px-3 py-1 text-sm ${
                      on ? "border-ink bg-ink text-white" : "border-rule-strong bg-sheet text-ink hover:border-ink"
                    }`}
                  >
                    {o}
                  </button>
                );
              })}
            </div>
          </fieldset>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            disabled={busy || chosen.length === 0}
            onClick={() => {
              say(
                "Please use these choices for this lesson. " +
                  chosen.map((c) => `${c.name}: ${picked[c.name].join(", ")}.`).join(" "),
              );
              setPicked({});
            }}
          >
            Tell the agent
          </Button>
          <span className="text-xs text-pencil">
            {chosen.length === 0
              ? "Nothing picked yet."
              : `${chosen.length} picked. The agent changes the lesson and tells you what it did.`}
          </span>
        </div>
      </div>
    </details>
  );
}

/** Objectives, the activity and the rules - the lesson itself. */
function WhatItTeaches({
  card,
  act,
  busy,
  open,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  open: boolean;
}) {
  // The steps the agent's own fill-ins point at, so each row can carry its check label.
  const check = card.status === "draft" ? stepsToCheck(card.to_check) : new Map<number, string[]>();
  return (
    <>
      {card.objectives.length > 0 && (
        <Row label="Students will">
          <ul className="list-disc space-y-0.5 pl-5">
            {card.objectives.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </Row>
      )}

      {card.steps.length > 0 && (
        <Row label="The activity">
          {(card.status === "draft" || open) && (
            <p className="mb-1.5 text-xs text-pencil">
              Depth is the kind of thinking a step asks for, 1 to 4. The agent proposes it; ask
              it to change any.
            </p>
          )}
          <ol className="space-y-0.5">
            {card.steps.map((s, i) => (
              <li key={`${s.name}-${i}`} className="flex gap-3">
                <span className="figures w-4 shrink-0 text-pencil">
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold text-ink">{s.name}</span>
                    <span className="text-xs text-pencil">
                      {KIND_WORDS[s.kind] ?? s.kind}
                    </span>
                    <DepthLabel depth={s.depth} set={s.depth_set} />
                    {check.has(i + 1) && (
                      <span
                        title={`The agent wrote this itself: ${check.get(i + 1)?.join(", ")}`}
                        className="rounded-full bg-amber-wash px-2 py-0.5 text-xs font-semibold text-amber"
                      >
                        check
                      </span>
                    )}
                  </span>
                  <span className="block text-pencil">{s.goal}</span>
                  {s.questions.length > 0 && (
                    <span className="mt-1 block space-y-0.5">
                      {s.questions.map((q) => (
                        <span key={q} className="block text-ink">
                          “{q}”
                        </span>
                      ))}
                    </span>
                  )}
                  {open && s.criteria.length > 0 && (
                    <span className="block text-pencil">
                      Counts as done when: {s.criteria.join("; ")}
                    </span>
                  )}
                  {open && s.answer && (
                    <span className="block text-pencil">
                      Answer, which students never see: <span className="text-ink">{s.answer}</span>
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </Row>
      )}

      {card.rules_in_words.length > 0 && (
        <Row label="How the agent will help">
          <ul className="list-disc space-y-0.5 pl-5">
            {card.rules_in_words.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {card.status !== "active" && (
            <p className="mt-1 text-xs text-pencil">
              Change any of these by saying so in the chat.
            </p>
          )}
        </Row>
      )}

      {/* The strategy is detail; the key terms and the support for this class always show. */}
      {((open && card.strategy) || card.key_terms.length > 0 || card.support) && (
        <Row label="How to teach it">
          <div className="space-y-1">
            {open && card.strategy && <p>{card.strategy}</p>}
            {card.key_terms.length > 0 && (
              <p>
                <span className="font-semibold">Key terms:</span> {card.key_terms.join(", ")}
              </p>
            )}
            {card.support && (
              <p>
                <span className="font-semibold">Support for this class:</span> {card.support}
              </p>
            )}
          </div>
        </Row>
      )}

      {open && (
        <>
          {card.assessment.length > 0 && (
            <Row label="Assessed on">
              <ul className="space-y-0.5">
                {card.assessment.map((c) => (
                  <li key={c.name}>
                    <span className="font-semibold">{c.name}</span>{" "}
                    <span className="figures text-pencil">/{c.max}</span>
                    {c.description && (
                      <span className="text-pencil">: {c.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            </Row>
          )}
          {card.rules_text && (
            <Row label="In your words">“{card.rules_text}”</Row>
          )}
        </>
      )}

      {card.materials.length > 0 && (
        <Row label="Material you gave it">
          <ul className="flex flex-wrap gap-2">
            {card.materials.map((m) => (
              <li
                key={m.id}
                className="flex items-center gap-2 rounded-full bg-sunken px-3 py-1 text-xs text-ink"
                title={
                  m.readable
                    ? "The agent can read this"
                    : "The agent cannot read this file"
                }
              >
                {m.filename}
                {!m.readable && (
                  <span className="text-amber">· unreadable</span>
                )}
                <button
                  type="button"
                  disabled={busy}
                  aria-label={`Remove ${m.filename}`}
                  title="The agent keeps the lesson; it just stops seeing this file"
                  onClick={() =>
                    act({ action: "delete_material", material_id: m.id })
                  }
                  className="text-pencil hover:text-red-pen"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </Row>
      )}
    </>
  );
}

/** How it has been taught, what it remembers, and getting rid of it. */
function LessonFooter({
  card,
  act,
  busy,
  open,
  onToggle,
  onApproach,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  open: boolean;
  onToggle: () => void;
  /** Offered only while the lesson has no approach: the row above shows it once it has one. */
  onApproach?: () => void;
}) {
  const [removing, setRemoving] = useState(false);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule pt-3 text-sm">
      <Button variant="quiet" onClick={onToggle}>
        {open ? "Hide the detail" : "Show every detail"}
      </Button>
      {onApproach && (
        <button onClick={onApproach} className={LINK}>
          Teaching approach
        </button>
      )}
      {removing ? (
        <span className="ml-auto flex flex-wrap items-center gap-2 text-ink">
          {removeWords(card)}
          <Button
            size="sm"
            variant="red"
            disabled={busy}
            onClick={() =>
              act({ action: "delete_lesson", lesson_id: card.lesson_id })
            }
          >
            Remove
          </Button>
          <Button size="sm" variant="plain" onClick={() => setRemoving(false)}>
            Keep it
          </Button>
        </span>
      ) : (
        <Button
          variant="red"
          disabled={busy}
          onClick={() => setRemoving(true)}
          className="ml-auto"
        >
          Remove this lesson
        </Button>
      )}
    </div>
  );
}
