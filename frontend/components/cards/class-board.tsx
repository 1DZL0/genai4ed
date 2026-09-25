"use client";

import { useState } from "react";
import type { ClassCard } from "@/lib/api";
import {
  Row,
  STATE_LOOK,
  STATE_TEXT,
  STATE_WORDS,
  Sheet,
  type Act,
  type StudentState,
} from "@/components/cards/parts";
import { Button, QueueKind, TimeLeft } from "@/components/ui";

/* ---------- the class ---------- */

const ORDER: StudentState[] = ["needs_you", "struggling", "working", "finished", "took_part", "not_started"];

export function ClassBoard({ card, act, busy }: { card: ClassCard; act: Act; busy: boolean }) {
  const running = card.status === "open" || card.status === "paused";
  // Over: there is nobody to walk over to, so everyone is shown from the start.
  const [everyone, setEveryone] = useState(!running);
  const [ending, setEnding] = useState(false);
  const sorted = [...card.students].sort(
    (a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.pseudonym.localeCompare(b.pseudonym),
  );
  // Only the ones a teacher would walk over to. The rest are a count until asked for.
  const wanted = sorted.filter((s) => s.state === "needs_you" || s.state === "struggling");
  const shown = everyone ? sorted : wanted;
  const counts = ORDER
    .map((state) => [state, card.students.filter((s) => s.state === state).length] as const)
    .filter(([, n]) => n > 0);

  return (
    <Sheet>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-serif text-xl font-semibold text-ink">
          {card.class_label} · {card.title}
        </h2>
        <p className="text-sm">
          {card.status === "paused" && <span className="font-semibold text-amber">Paused · </span>}
          <TimeLeft closesAt={card.closes_at} status={card.status} />
        </p>
      </div>

      <p className="mt-1 flex flex-wrap gap-x-3 text-sm">
        {counts.map(([state, n]) => (
          <span key={state} className={STATE_TEXT[state]}>
            <span className="figures font-semibold">{n}</span> {STATE_WORDS[state].toLowerCase()}
          </span>
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
            variant="quiet"
            disabled={busy}
            onClick={() => act({ action: "show_outcomes", session_id: card.session_id })}
          >
            Outcomes
          </Button>
        )}
      </div>

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
                  className="font-semibold text-ink underline underline-offset-4"
                >
                  {a.pseudonym}
                </button>
                <QueueKind kind={a.kind} priority={a.priority} />
                <span className="text-pencil">{a.summary}</span>
                <button
                  disabled={busy}
                  onClick={() => act({ action: "acknowledge", exception_id: a.id })}
                  className="ml-auto text-xs text-pencil underline underline-offset-4 hover:text-ink"
                >
                  Dealt with
                </button>
              </li>
            ))}
          </ul>
        </Row>
      )}

      {card.patterns.length > 0 && (
        <Row label="Across the class">
          <ul className="space-y-0.5">
            {card.patterns.map((p) => (
              <li key={p.note}>
                {p.note} — <span className="text-pencil">{p.students.join(", ")}</span>{" "}
                <button
                  disabled={busy}
                  onClick={() => act({ action: "follow_up", text: p.note })}
                  className="text-xs text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink"
                >
                  Draft a follow-up
                </button>
              </li>
            ))}
          </ul>
        </Row>
      )}

      <div className="py-2">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-xs font-bold text-pencil">
            {everyone ? "Everyone" : wanted.length > 0 ? "Worth a look" : ""}
          </p>
          <button
            onClick={() => setEveryone(!everyone)}
            className="text-xs text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink"
          >
            {everyone ? "Just the ones who need me" : `Show all ${card.students.length}`}
          </button>
        </div>
        {shown.length > 0 ? (
          <ul className="mt-1 flex flex-wrap gap-2">
            {shown.map((s) => (
              <li key={s.student_id}>
                <button
                  disabled={busy}
                  onClick={() =>
                    act({
                      action: "show_student",
                      session_id: card.session_id,
                      student_id: s.student_id,
                    })
                  }
                  title={`${STATE_WORDS[s.state]}${s.step_name ? ` · ${s.step_name}` : ""}${s.note ? ` · ${s.note}` : ""}`}
                  className={`rounded-full border bg-sheet px-3 py-1 text-xs hover:border-ink ${STATE_LOOK[s.state]} ${STATE_TEXT[s.state]}`}
                >
                  <span className="font-semibold">{s.pseudonym}</span>
                  <span className="text-pencil"> · {STATE_WORDS[s.state]}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-pencil">
            {running ? "Nobody needs you at the moment." : "The lesson is over."}
          </p>
        )}
      </div>

      {card.notable.length > 0 && everyone && (
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
