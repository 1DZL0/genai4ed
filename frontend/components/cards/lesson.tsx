"use client";

import { useId, useState } from "react";
import type { LessonCard } from "@/lib/api";
import { APPROACHES, approachName } from "@/lib/approaches";
import { Row, Sheet, type Act } from "@/components/cards/parts";
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
          className={`text-sm font-semibold ${approved ? "text-tick" : "text-amber"}`}
        >
          {approved
            ? "Ready to teach"
            : card.approved_lesson_id
              ? "A change you haven't approved"
              : "Draft"}
        </span>
      </div>

      <UnitRow card={card} act={act} busy={busy} />
      <ApproachRow
        card={card}
        act={act}
        busy={busy}
        say={say}
        open={approachOpen}
        onOpen={() => setApproachOpen(true)}
        onClose={() => setApproachOpen(false)}
      />
      <Stages card={card} />
      <WhatYouCanDo card={card} act={act} busy={busy} />
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

/** Which unit the lesson is part of, and a box to change that. A unit is only a name for now. */
function UnitRow({ card, act, busy }: { card: LessonCard; act: Act; busy: boolean }) {
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(card.unit ?? "");

  async function put(unit: string) {
    await act({ action: "set_unit", lesson_id: card.lesson_id, text: unit });
    setEditing(false);
  }

  if (!editing) {
    return (
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 rounded-[var(--radius-control)] bg-sunken px-3 py-1.5 text-sm">
        {card.unit ? (
          <>
            <span className="text-pencil">Part of the unit</span>
            <span className="font-semibold text-ink">{card.unit}</span>
          </>
        ) : (
          <span className="text-pencil">Not in a unit</span>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setName(card.unit ?? "");
            setEditing(true);
          }}
          className={`${LINK} ml-auto disabled:opacity-40`}
        >
          {card.unit ? "Change" : "Add to a unit"}
        </button>
      </div>
    );
  }
  return (
    <form
      className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] bg-sunken px-3 py-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        void put(name);
      }}
    >
      <label htmlFor={`${id}-unit`} className="text-pencil">
        Unit
      </label>
      <input
        id={`${id}-unit`}
        list={`${id}-units`}
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={80}
        placeholder="Percentages"
        className="h-8 min-w-0 flex-1 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
      />
      <datalist id={`${id}-units`}>
        {card.units.map((u) => (
          <option key={u} value={u} />
        ))}
      </datalist>
      <Button size="sm" type="submit" disabled={busy || name.trim() === (card.unit ?? "")}>
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
    </form>
  );
}

/** The teaching approach a lesson is taught by, for a side-by-side comparison. Shown only once
 * set; until then it is reached from a small link in the footer. */
function ApproachRow({
  card,
  act,
  busy,
  say,
  open,
  onOpen,
  onClose,
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  say?: (words: string) => void;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const id = useId();
  const [pick, setPick] = useState(card.approach ?? "");
  if (!open && !card.approach) return null;

  async function save() {
    await act({ action: "set_approach", lesson_id: card.lesson_id, text: pick });
    // The agent now sees the approach in its instructions; it is asked to redo the draft under it.
    if (pick && say) say("Rebuild the steps and the rules for this teaching approach, keeping my content.");
    onClose();
  }

  if (!open) {
    return (
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 rounded-[var(--radius-control)] bg-sunken px-3 py-1.5 text-sm">
        <span className="text-pencil">Taught by</span>
        <span className="font-semibold text-ink">{approachName(card.approach)}</span>
        <button
          type="button"
          disabled={busy}
          title="A copy with the same steps, questions and marks, taught the other way"
          onClick={() =>
            act({
              action: "copy_with_approach",
              lesson_id: card.lesson_id,
              text: card.approach === "direct" ? "inquiry" : "direct",
            })
          }
          className={`${LINK} ml-auto disabled:opacity-40`}
        >
          Make the other version
        </button>
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
  const caption = card.live
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
  const chosen = card.classes.find((c) => c.id === klass);
  const ready = card.missing.length === 0;
  const approved = card.status === "active";

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-rule py-2.5">
      {!approved && (
        <Button
          disabled={busy || !ready}
          onClick={() => act({ action: "approve", lesson_id: card.lesson_id })}
        >
          Approve
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
                <a href="/teacher/classes" className={LINK}>
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
          To approve it, it still needs {card.missing.join(", ")}. Say it in the
          chat and the agent adds it.
        </span>
      )}
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
          <ol className="space-y-0.5">
            {card.steps.map((s, i) => (
              <li key={`${s.name}-${i}`} className="flex gap-3">
                <span className="figures w-4 shrink-0 text-pencil">
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <span className="font-semibold text-ink">{s.name}</span>{" "}
                  <span className="text-xs text-pencil">
                    {KIND_WORDS[s.kind] ?? s.kind}
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
                      {s.has_reference &&
                        ". It holds an answer students never see"}
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

      {open && (
        <>
          {card.strategy && <Row label="How to teach it">{card.strategy}</Row>}
          {card.assessment.length > 0 && (
            <Row label="Assessed on">
              <ul className="space-y-0.5">
                {card.assessment.map((c) => (
                  <li key={c.name}>
                    <span className="font-semibold">{c.name}</span>{" "}
                    <span className="figures text-pencil">/{c.max}</span>
                    {c.description && (
                      <span className="text-pencil"> — {c.description}</span>
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
      {card.runs
        .filter((r) => r.status === "closed")
        .slice(0, 3)
        .map((r) => (
          <button
            key={r.session_id}
            disabled={busy}
            onClick={() =>
              act({ action: "show_outcomes", session_id: r.session_id })
            }
            className={LINK}
          >
            Taught {r.class_label}
            {r.closed_at
              ? `, ended ${clockTime(r.closed_at)}`
              : ", running now"}
            {r.outcomes_to_confirm > 0 &&
              ` · ${r.outcomes_to_confirm} to confirm`}
          </button>
        ))}
      {onApproach && (
        <button onClick={onApproach} className={LINK}>
          Teaching approach
        </button>
      )}
      {removing ? (
        <span className="ml-auto flex flex-wrap items-center gap-2 text-ink">
          {card.runs.length > 0
            ? "Keep the lessons already taught and remove it?"
            : "Remove it?"}
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
