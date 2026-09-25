"use client";

import { useId, useState } from "react";
import type { LessonCard } from "@/lib/api";
import { Row, Sheet, type Act } from "@/components/cards/parts";
import { Button, SubjectName, clockTime } from "@/components/ui";

/** A lesson as the teacher works on it: what it is, what they can do with it, and what the agent will teach. */

const LINK = "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink";

export function Lesson({ card, act, busy }: { card: LessonCard; act: Act; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const approved = card.status === "active";

  return (
    <Sheet>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <SubjectName subject={card.subject} />
          <h2 className="font-serif text-xl leading-snug font-semibold text-ink">{card.title}</h2>
          <p className="text-sm text-pencil">
            {card.steps.length} steps, {card.duration_minutes} minutes
            {card.assessment.length > 0 &&
              ` · marked on ${card.assessment.map((c) => `${c.name} (${c.max})`).join(", ")}`}
          </p>
        </div>
        <span className={`text-sm font-semibold ${approved ? "text-tick" : "text-amber"}`}>
          {approved
            ? "Ready to teach"
            : card.approved_lesson_id
              ? "A change you haven't approved"
              : "Draft"}
        </span>
      </div>

      <WhatYouCanDo card={card} act={act} busy={busy} />
      <WhatItTeaches card={card} act={act} busy={busy} open={open} />
      <LessonFooter card={card} act={act} busy={busy} open={open} onToggle={() => setOpen(!open)} />
    </Sheet>
  );
}

/** Approving it, and running it with a class. Above the detail, not under it. */
function WhatYouCanDo({ card, act, busy }: { card: LessonCard; act: Act; busy: boolean }) {
  const id = useId();
  const [klass, setKlass] = useState("");
  const ready = card.missing.length === 0;
  const approved = card.status === "active";

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-rule py-2.5">
      {!approved && (
        <Button
          size="sm"
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
            className="h-8 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
          >
            <option value="">Choose a class</option>
            {card.classes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.students})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="quiet"
            disabled={busy || !klass}
            onClick={() => act({ action: "run", lesson_id: card.lesson_id, class_id: klass })}
          >
            Start now
          </Button>
        </>
      )}
      {card.live && (
        <Button
          size="sm"
          variant="quiet"
          disabled={busy}
          onClick={() => act({ action: "show_class", session_id: card.live!.session_id })}
        >
          Running with {card.live.class_label}
        </Button>
      )}
      {/* What to do next, said once, where the buttons are. */}
      {!ready ? (
        <span className="text-xs text-amber">Still needs {card.missing.join(", ")}.</span>
      ) : !approved ? (
        <span className="text-xs text-pencil">Approve it and it&apos;s ready for a class.</span>
      ) : !card.live && !klass ? (
        <span className="text-xs text-pencil">Choose a class to start it.</span>
      ) : null}
    </div>
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
                <span className="figures w-4 shrink-0 text-pencil">{i + 1}</span>
                <span className="min-w-0">
                  <span className="font-semibold text-ink">{s.name}</span>{" "}
                  <span className="text-pencil">({s.kind})</span>
                  {open && <span className="block text-pencil">{s.goal}</span>}
                  {open && s.criteria.length > 0 && (
                    <span className="block text-pencil">
                      Good answer: {s.criteria.join("; ")}
                      {s.has_reference && " · has an answer students never see"}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </Row>
      )}

      {card.rules_in_words.length > 0 && (
        <Row label="Rules for the agent">
          <ul className="list-disc space-y-0.5 pl-5">
            {card.rules_in_words.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
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
                    {c.description && <span className="text-pencil"> — {c.description}</span>}
                  </li>
                ))}
              </ul>
            </Row>
          )}
          {card.rules_text && <Row label="In your words">“{card.rules_text}”</Row>}
        </>
      )}

      {card.materials.length > 0 && (
        <Row label="Material you gave it">
          <ul className="flex flex-wrap gap-2">
            {card.materials.map((m) => (
              <li
                key={m.id}
                className="flex items-center gap-2 rounded-full bg-sunken px-3 py-1 text-xs text-ink"
                title={m.readable ? "The agent can read this" : "The agent cannot read this file"}
              >
                {m.filename}
                {!m.readable && <span className="text-amber">· unreadable</span>}
                <button
                  type="button"
                  disabled={busy}
                  aria-label={`Remove ${m.filename}`}
                  title="The agent keeps the lesson; it just stops seeing this file"
                  onClick={() => act({ action: "delete_material", material_id: m.id })}
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
}: {
  card: LessonCard;
  act: Act;
  busy: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const [removing, setRemoving] = useState(false);

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule pt-2.5 text-xs">
      <button
        onClick={onToggle}
        className={LINK}
      >
        {open ? "Less detail" : "Everything in the lesson"}
      </button>
      {card.runs
        .filter((r) => r.status === "closed")
        .slice(0, 3)
        .map((r) => (
          <button
            key={r.session_id}
            disabled={busy}
            onClick={() => act({ action: "show_outcomes", session_id: r.session_id })}
            className={LINK}
          >
            Taught {r.class_label}
            {r.closed_at ? `, ended ${clockTime(r.closed_at)}` : ", running now"}
            {r.outcomes_to_confirm > 0 && ` · ${r.outcomes_to_confirm} to confirm`}
          </button>
        ))}
      {!card.study && (
        <label className="ml-auto flex items-center gap-2 text-pencil">
          <input
            type="checkbox"
            checked={card.use_past_lessons}
            disabled={busy}
            onChange={(e) =>
              act({ action: "use_past_lessons", lesson_id: card.lesson_id, value: e.target.checked })
            }
          />
          Use what it learned about each student before
        </label>
      )}
      {removing ? (
        <span className="flex items-center gap-2 text-ink">
          {card.runs.length > 0 ? "Keep the lessons already taught and remove it?" : "Remove it?"}
          <Button
            size="sm"
            variant="red"
            disabled={busy}
            onClick={() => act({ action: "delete_lesson", lesson_id: card.lesson_id })}
          >
            Remove
          </Button>
          <Button size="sm" variant="plain" onClick={() => setRemoving(false)}>
            Keep it
          </Button>
        </span>
      ) : (
        <button
          onClick={() => setRemoving(true)}
          className="text-pencil underline decoration-rule-strong underline-offset-4 hover:text-red-pen"
        >
          Remove this lesson
        </button>
      )}
    </div>
  );
}
