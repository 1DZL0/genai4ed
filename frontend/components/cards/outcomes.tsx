"use client";

import { useId, useState } from "react";
import type { Outcome, OutcomesCard } from "@/lib/api";
import { Sheet, type Act } from "@/components/cards/parts";
import { Button } from "@/components/ui";

/* ---------- outcomes the teacher confirms ---------- */

export function Outcomes({ card, act, busy }: { card: OutcomesCard; act: Act; busy: boolean }) {
  return (
    <Sheet>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-serif text-xl font-semibold text-ink">
          {card.class_label} · {card.title}
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
      {card.summary && <p className="mt-1 text-sm text-ink">{card.summary}</p>}

      {card.outcomes.length === 0 ? (
        <div className="mt-3">
          {!card.took_part ? (
            <p className="text-sm text-pencil">
              Nobody took part in this lesson, so there is nothing to judge.
            </p>
          ) : card.can_suggest ? (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => act({ action: "suggest_outcomes", session_id: card.session_id })}
            >
              Suggest outcomes
            </Button>
          ) : (
            <p className="text-sm text-pencil">
              {card.status === "closed"
                ? "This lesson has nothing to assess."
                : "End the lesson before looking at outcomes."}
            </p>
          )}
        </div>
      ) : (
        <ul role="list" className="mt-2 divide-y divide-rule">
          {card.outcomes.map((o) => (
            <OutcomeRow key={o.id} outcome={o} sessionId={card.session_id} act={act} busy={busy} />
          ))}
        </ul>
      )}

      {card.students_without_outcome.length > 0 && (
        <p className="mt-3 text-xs text-pencil">
          No outcome suggested for {card.students_without_outcome.join(", ")}.
        </p>
      )}
      <p className="mt-3 text-xs text-faint">
        The agent suggests; nothing reaches a student until you confirm it.
      </p>
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
          {confirmed ? outcome.confirmed_total : total} / {outcome.out_of}
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
