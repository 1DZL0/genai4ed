"use client";

import { useState } from "react";
import type { ClassCard } from "@/lib/api";
import {
  ClassName,
  Row,
  STATE_DOT,
  STATE_LOOK,
  STATE_TEXT,
  STATE_WORDS,
  Sheet,
  StatePill,
  type Act,
  type StudentState,
} from "@/components/cards/parts";
import { TeachAgain } from "@/components/cards/teach-again";
import { Button, QueueKind, TimeLeft } from "@/components/ui";

/* ---------- the class ---------- */

const ORDER: StudentState[] = ["needs_you", "struggling", "working", "finished", "took_part", "not_started"];

export function ClassBoard({ card, act, busy }: { card: ClassCard; act: Act; busy: boolean }) {
  const running = card.status === "open" || card.status === "paused";
  const [ending, setEnding] = useState(false);
  const sorted = [...card.students].sort(
    (a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.pseudonym.localeCompare(b.pseudonym),
  );
  const counts = ORDER
    .map((state) => [state, card.students.filter((s) => s.state === state).length] as const)
    .filter(([, n]) => n > 0);

  return (
    <Sheet>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-serif text-xl font-semibold text-ink">
          <ClassName label={card.class_label} /> · {card.title}
        </h2>
        <p className="text-sm">
          {card.status === "paused" && <span className="font-semibold text-amber">Paused · </span>}
          <TimeLeft closesAt={card.closes_at} status={card.status} />
        </p>
      </div>

      <p className="mt-2 flex flex-wrap gap-1.5">
        {counts.map(([state, n]) => (
          <StatePill key={state} state={state} count={n} />
        ))}
      </p>

      <div className="mt-2 flex flex-wrap gap-2 border-y border-rule py-2.5">
        {card.status === "open" && (
          <Button
            size="sm"
            variant="quiet"
            disabled={busy}
            onClick={() => act({ action: "pause", session_id: card.session_id })}
          >
            Pause
          </Button>
        )}
        {card.status === "paused" && (
          <Button
            size="sm"
            variant="quiet"
            disabled={busy}
            onClick={() => act({ action: "resume", session_id: card.session_id })}
          >
            Carry on
          </Button>
        )}
        {running &&
          (ending ? (
            <span className="flex items-center gap-2 text-sm text-ink">
              End it for the whole class? It can&apos;t be restarted.
              <Button
                size="sm"
                variant="red"
                disabled={busy}
                onClick={() => act({ action: "end", session_id: card.session_id })}
              >
                End it
              </Button>
              <Button size="sm" variant="plain" onClick={() => setEnding(false)}>
                Keep going
              </Button>
            </span>
          ) : (
            <Button size="sm" variant="quiet" disabled={busy} onClick={() => setEnding(true)}>
              End the lesson
            </Button>
          ))}
        {!running && (
          <Button
            size="sm"
            disabled={busy}
            onClick={() => act({ action: "show_outcomes", session_id: card.session_id })}
          >
            Summary and notes on each student
          </Button>
        )}
      </div>
      {!running && card.teach_again && (
        <TeachAgain data={card.teach_again} act={act} busy={busy} />
      )}

      {card.alerts.length > 0 && (
        <Row label={running ? "Needs you" : "Raised during the lesson"}>
          <ul className="space-y-1.5">
            {card.alerts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-baseline gap-x-2">
                <button
                  disabled={busy}
                  onClick={() =>
                    act({
                      action: "show_student",
                      session_id: card.session_id,
                      student_id: a.student_id,
                    })
                  }
                  className="inline-flex h-7 items-center rounded-full border border-rule-strong bg-sheet px-2.5 text-xs font-semibold text-ink hover:border-ink"
                >
                  {a.pseudonym}
                </button>
                <QueueKind kind={a.kind} priority={a.priority} />
                <span className="text-pencil">{a.summary}</span>
                <Button
                  size="sm"
                  variant="quiet"
                  disabled={busy}
                  onClick={() => act({ action: "acknowledge", exception_id: a.id })}
                  className="ml-auto"
                >
                  Dealt with
                </Button>
              </li>
            ))}
          </ul>
        </Row>
      )}

      {card.patterns.length > 0 && (
        <Row label="Across the class">
          <ul className="space-y-2">
            {card.patterns.map((p) => (
              <li key={p.note} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>
                  {p.note}: <span className="text-pencil">{p.students.join(", ")}</span>
                </span>
                <Button
                  size="sm"
                  variant="pill"
                  disabled={busy}
                  onClick={() => act({ action: "follow_up", text: p.note })}
                >
                  Draft a follow-up lesson
                </Button>
              </li>
            ))}
          </ul>
        </Row>
      )}

      <div className="py-3">
        <p className="text-sm font-semibold text-ink">Students</p>
        <p className="text-xs text-pencil">
          Press a name to see their work and tell the agent what to do with them.
        </p>
        {sorted.length > 0 ? (
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {sorted.map((s) => (
              <li key={s.student_id} className="min-w-0">
                <button
                  disabled={busy}
                  onClick={() =>
                    act({
                      action: "show_student",
                      session_id: card.session_id,
                      student_id: s.student_id,
                    })
                  }
                  className={`flex h-full w-full flex-col items-start gap-0.5 rounded-[var(--radius-control)] border-2 bg-sheet px-3 py-2 text-left hover:border-ink ${STATE_LOOK[s.state]}`}
                >
                  <span className="flex w-full items-baseline justify-between gap-2">
                    <span className="truncate font-semibold text-ink">{s.pseudonym}</span>
                    <span
                      className={`inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold ${STATE_TEXT[s.state]}`}
                    >
                      <span aria-hidden="true" className={`size-2 rounded-full ${STATE_DOT[s.state]}`} />
                      {STATE_WORDS[s.state]}
                    </span>
                  </span>
                  {s.turns > 0 && s.step_name && (
                    <span className="text-xs text-pencil">
                      {s.state === "finished" ? "Finished every step" : `On “${s.step_name}”`}
                    </span>
                  )}
                  {s.note && <span className="line-clamp-2 text-xs text-pencil">{s.note}</span>}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-pencil">Nobody is in this class yet.</p>
        )}
      </div>

      {card.notable.length > 0 && (
        <Row label="Worth knowing">
          <ul className="space-y-0.5 text-pencil">
            {card.notable.slice(-5).map((n, i) => (
              <li key={`${n.pseudonym}-${i}`}>
                <span className="font-semibold text-ink">{n.pseudonym}</span> {n.note}
              </li>
            ))}
          </ul>
        </Row>
      )}
    </Sheet>
  );
}
