"use client";

import { useId, useState } from "react";
import type { Outcome, OutcomesCard } from "@/lib/api";
import { ClassName, Sheet, type Act } from "@/components/cards/parts";
import { TeachAgain } from "@/components/cards/teach-again";
import { Button, QueueKind } from "@/components/ui";
import { DEPTH_PLAIN } from "@/components/quick-choices";

/* ---------- outcomes the teacher confirms ---------- */

export function Outcomes({ card, act, busy }: { card: OutcomesCard; act: Act; busy: boolean }) {
  return (
    <Sheet>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-serif text-xl font-semibold text-ink">
          <ClassName label={card.class_label} /> · {card.title}
        </h2>
        <span className="flex items-center gap-3 text-sm text-pencil">
          {card.status === "closed" ? "Ended" : "Still running"}
          <Button
            size="sm"
            variant="plain"
            disabled={busy}
            onClick={() => act({ action: "show_class", session_id: card.session_id })}
          >
            The class
          </Button>
        </span>
      </div>
      {card.alerts.length > 0 && (
        <div className="mt-3 rounded-[var(--radius-control)] border border-amber/40 bg-amber-wash px-3 py-2.5">
          <p className="text-xs font-bold text-ink">
            Still open from this lesson ({card.alerts.length})
          </p>
          <ul className="mt-1 space-y-1.5 text-sm text-ink">
            {card.alerts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="min-w-0">
                  <QueueKind kind={a.kind} priority={a.priority} />{" "}
                  <span className="font-semibold">{a.pseudonym}</span>: {a.summary}
                </span>
                <Button
                  size="sm"
                  variant="quiet"
                  disabled={busy}
                  onClick={() => act({ action: "acknowledge", exception_id: a.id })}
                >
                  Dealt with
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {card.summary && (
        <div className="mt-3 rounded-[var(--radius-control)] bg-sunken px-3 py-2.5">
          <p className="text-xs font-bold text-pencil">How the class did</p>
          <p className="mt-0.5 whitespace-pre-line text-sm text-ink">{card.summary}</p>
        </div>
      )}

      {card.outcomes.length === 0 ? (
        <div className="mt-3">
          {!card.took_part ? (
            <p className="text-sm text-pencil">
              Nobody took part in this lesson, so there is nothing to judge.
            </p>
          ) : card.can_suggest ? (
            <>
              <p className="mb-2 text-sm text-pencil">
                The agent writes how the class did and a note on each student who wrote something
                {card.marked ? ", with suggested marks" : ""}. You check each one; once you confirm
                it, the student sees the note (what went well and what to look at again)
                {card.marked ? ", the marks" : ""} and your comment.
              </p>
              <Button
                disabled={busy}
                onClick={() => act({ action: "suggest_outcomes", session_id: card.session_id })}
              >
                Write the summary
              </Button>
            </>
          ) : (
            <p className="text-sm text-pencil">
              {card.status === "closed"
                ? "This lesson has nothing to assess."
                : "End the lesson before looking at outcomes."}
            </p>
          )}
        </div>
      ) : (
        <ul role="list" className="mt-3 divide-y divide-rule" aria-label="Each student">
          {card.outcomes.map((o) => (
            <OutcomeRow key={o.id} outcome={o} sessionId={card.session_id} act={act} busy={busy} />
          ))}
        </ul>
      )}

      {/* Only once the agent has written its suggestions: before that nobody has one. */}
      {card.outcomes.length > 0 && card.students_without_outcome.length > 0 && (
        <p className="mt-3 text-xs text-pencil">
          No outcome suggested for {card.students_without_outcome.join(", ")}.
        </p>
      )}
      <p className="mt-3 text-xs text-faint">
        The agent suggests; nothing reaches a student until you confirm it.
      </p>
      {card.status === "closed" && card.teach_again && (
        <TeachAgain data={card.teach_again} act={act} busy={busy} />
      )}
    </Sheet>
  );
}

function OutcomeRow({
  outcome,
  sessionId,
  act,
  busy,
}: {
  outcome: Outcome;
  sessionId: string;
  act: Act;
  busy: boolean;
}) {
  const id = useId();
  const confirmed = outcome.status === "confirmed";
  const criteria: Outcome["suggested"]["criteria"] =
    (confirmed ? outcome.confirmed?.criteria : outcome.suggested.criteria) ?? [];
  const [points, setPoints] = useState<Record<string, number>>(
    Object.fromEntries(criteria.map((c) => [c.name, c.points])),
  );
  const [comment, setComment] = useState(outcome.comment ?? "");
  const total = Object.values(points).reduce((a, b) => a + b, 0);

  return (
    <li className="py-3 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink">{outcome.pseudonym}</span>
        <span className="figures text-sm text-pencil">
          {outcome.out_of > 0 && `${confirmed ? outcome.confirmed_total : total} / ${outcome.out_of}`}
          {confirmed && <span className="ml-2 font-semibold text-tick">Confirmed</span>}
        </span>
      </div>
      <ul className="mt-1 space-y-1">
        {criteria.map((c) => (
          <li key={c.name} className="flex flex-wrap items-baseline gap-2 text-sm">
            <span className="w-36 shrink-0 text-ink">{c.name}</span>
            {confirmed ? (
              <span className="figures text-pencil">
                {c.points} / {c.max}
              </span>
            ) : (
              <>
                <label className="sr-only" htmlFor={`${id}-${c.name}`}>
                  {c.name} out of {c.max}
                </label>
                <input
                  id={`${id}-${c.name}`}
                  type="number"
                  min={0}
                  max={c.max}
                  value={points[c.name] ?? c.points}
                  onChange={(e) =>
                    setPoints({ ...points, [c.name]: Math.max(0, Math.min(c.max, Number(e.target.value))) })
                  }
                  className="figures h-8 w-16 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
                />
                <span className="figures text-pencil">/ {c.max}</span>
              </>
            )}
            {typeof c.reason === "string" && <span className="text-pencil">{c.reason}</span>}
          </li>
        ))}
      </ul>
      {outcome.suggested.keep && (
        <p className="mt-1 text-sm text-pencil">Did well: {outcome.suggested.keep}</p>
      )}
      {outcome.suggested.develop.length > 0 && (
        <p className="text-sm text-pencil">
          To work on: {outcome.suggested.develop.map((d) => d.replace(/\.$/, "")).join("; ")}
        </p>
      )}
      {outcome.suggested.depth && (
        <p className="text-sm text-pencil">Depth: {outcome.suggested.depth}</p>
      )}
      {typeof outcome.suggested.deepest === "number" && (
        <p className="text-sm text-pencil">
          Deepest: {DEPTH_PLAIN[outcome.suggested.deepest]} ({outcome.suggested.deepest})
        </p>
      )}
      {!confirmed && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`${id}-comment`}>
            A comment for {outcome.pseudonym}
          </label>
          <input
            id={`${id}-comment`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="A comment, in your words"
            className="h-8 flex-1 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink placeholder:text-faint"
          />
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              act({
                action: "confirm_outcome",
                session_id: sessionId,
                outcome_id: outcome.id,
                points,
                comment: comment.trim() || null,
              })
            }
          >
            Confirm
          </Button>
        </div>
      )}
    </li>
  );
}
