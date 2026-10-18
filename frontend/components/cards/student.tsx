"use client";

import { useId, useState } from "react";
import type { StudentCard } from "@/lib/api";
import { Row, STATE_TEXT, STATE_WORDS, Sheet, type Act } from "@/components/cards/parts";
import { Button, QueueKind, Tick, clockTime } from "@/components/ui";

/* ---------- one student ---------- */

/** What teachers most often want for one student, ready to send or edit. */
const GUIDE_IDEAS = [
  "Move them on to the next question.",
  "Show them the answer and explain it.",
  "Give them a hint.",
  "Tell them to take a short break.",
  "Ask them to explain their thinking.",
];

const JUDGMENT_WORDS: Record<string, string> = {
  met: "met",
  partial: "partly",
  not_met: "not yet",
  unclear: "unclear",
};

export function Student({ card, act, busy }: { card: StudentCard; act: Act; busy: boolean }) {
  const id = useId();
  const [guidance, setGuidance] = useState("");
  const [tell, setTell] = useState(false);
  const [evidence, setEvidence] = useState(false);
  const open = card.session_status !== "closed";
  const go = (studentId: string) =>
    act({ action: "show_student", session_id: card.session_id, student_id: studentId });

  return (
    <Sheet>
      {/* Getting around the class first: back to everyone, or straight to anyone. */}
      <nav aria-label="The rest of the class" className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="quiet"
          disabled={busy}
          onClick={() => act({ action: "show_class", session_id: card.session_id })}
        >
          ← The whole class
        </Button>
        <label htmlFor={`${id}-jump`} className="sr-only">
          Go to another student
        </label>
        <select
          id={`${id}-jump`}
          value={card.student_id}
          disabled={busy}
          onChange={(e) => go(e.target.value)}
          className="h-8 min-w-0 flex-1 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
        >
          {card.classmates.map((c) => (
            <option key={c.student_id} value={c.student_id}>
              {c.pseudonym} · {STATE_WORDS[c.state]}
            </option>
          ))}
        </select>
      </nav>

      <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-serif text-2xl font-semibold text-ink">{card.pseudonym}</h2>
        <span className={`text-base font-semibold ${STATE_TEXT[card.state]}`}>
          {STATE_WORDS[card.state]}
        </span>
      </div>

      <ul className="mt-1 space-y-0.5 text-base text-ink">
        {card.summary.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {card.alerts.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label={`What needs you about ${card.pseudonym}`}>
          {card.alerts.map((a) => (
            <li
              key={a.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius-control)] border border-red-pen/40 bg-red-pen-wash px-3 py-2 text-sm"
            >
              <QueueKind kind={a.kind} priority={1} />
              <span className="min-w-0 flex-1 text-ink">{a.summary}</span>
              <Button
                size="sm"
                variant="quiet"
                disabled={busy}
                onClick={() =>
                  act({
                    action: "acknowledge",
                    exception_id: a.id,
                    student_id: card.student_id,
                  })
                }
              >
                Dealt with
              </Button>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="mt-4 rounded-[var(--radius-control)] border border-rule bg-sunken p-3">
          <label htmlFor={`${id}-guide`} className="text-sm font-semibold text-ink">
            Tell the agent what to do with {card.pseudonym}
          </label>
          <p className="text-xs text-pencil">
            The agent writes to {card.pseudonym} straight away. Pick one or write your own.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {GUIDE_IDEAS.map((idea) => (
              <button
                key={idea}
                type="button"
                onClick={() => setGuidance(idea)}
                className="rounded-full border border-rule-strong bg-sheet px-3 py-1 text-sm text-ink hover:border-ink"
              >
                {idea}
              </button>
            ))}
          </div>
          <textarea
            id={`${id}-guide`}
            rows={2}
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            placeholder="e.g. Ask them to explain each step before moving on."
            className="mt-2 w-full resize-none rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-ink focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button
              disabled={busy || !guidance.trim()}
              onClick={async () => {
                await act({
                  action: "guide",
                  session_id: card.session_id,
                  student_id: card.student_id,
                  text: guidance.trim(),
                  show_to_student: tell,
                });
                setGuidance("");
              }}
            >
              Send
            </Button>
            <label className="flex items-center gap-2 text-sm text-pencil">
              <input type="checkbox" checked={tell} onChange={(e) => setTell(e.target.checked)} />
              Also show {card.pseudonym} my words
            </label>
          </div>
        </div>
      )}

      {(card.previous || card.next) && (
        <div className="mt-3 flex gap-2">
          {card.previous && (
            <Button size="sm" variant="quiet" disabled={busy} onClick={() => go(card.previous!.student_id)}>
              ← {card.previous.pseudonym}
            </Button>
          )}
          {card.next && (
            <Button
              size="sm"
              variant="quiet"
              disabled={busy}
              onClick={() => go(card.next!.student_id)}
              className="ml-auto"
            >
              {card.next.pseudonym} →
            </Button>
          )}
        </div>
      )}

      {card.steps.length > 0 && (
        <Row label="Their progress">
          <ol className="space-y-1">
            {card.steps.map((s, i) => (
              <li key={`${s.name}-${i}`} className="flex items-baseline gap-2">
                {s.judgment === "met" ? <Tick className="size-4 shrink-0" /> : <span className="figures w-4 shrink-0 text-pencil">{i + 1}</span>}
                <span className={s.current ? "font-semibold text-ink" : "text-ink"}>{s.name}</span>
                {s.judgment && <span className="text-pencil">: {JUDGMENT_WORDS[s.judgment] ?? s.judgment}</span>}
                {s.attempts > 1 && <span className="figures text-pencil">· {s.attempts} answers</span>}
              </li>
            ))}
          </ol>
        </Row>
      )}

      {card.knowledge.length > 0 && (
        <Row label="Across their lessons">
          <ul className="space-y-0.5">
            {card.knowledge.map((k) => (
              <li key={k.topic}>
                <span className="font-semibold">{k.topic}</span>{" "}
                <span className="figures text-pencil">
                  {k.met} of {k.judged} answers met
                </span>
                {k.misconceptions.length > 0 && (
                  <span className="text-pencil">
                    {" "}
                    · has shown: {k.misconceptions.map((m) => m.replace(/\.$/, "")).join("; ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Row>
      )}

      {card.evidence.length > 0 && (
        <div className="py-2">
          <button
            onClick={() => setEvidence(!evidence)}
            className="text-xs font-bold text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink"
          >
            {evidence ? "Hide the evidence" : `The evidence behind this (${card.evidence.length})`}
          </button>
          {evidence && (
            <ul className="mt-2 space-y-1 text-sm">
              {card.evidence.map((e, i) => (
                <li key={`${e.at}-${i}`}>
                  <span className="figures text-xs text-faint">{clockTime(e.at)}</span>{" "}
                  <span className="text-ink">{e.text}</span>
                  {e.detail && <span className="text-pencil">: {e.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {card.conversation ? (
        <Row label="What they and the agent said">
          <ol className="space-y-1.5">
            {card.conversation.map((line, i) => (
              <li key={i} className={line.who === "teacher_only" ? "text-pencil italic" : ""}>
                <span className="text-xs font-bold text-pencil">
                  {line.who === "student" ? card.pseudonym : line.who === "agent" ? "Agent" : "Note"}
                </span>{" "}
                <span className="whitespace-pre-line">{line.text}</span>
              </li>
            ))}
            {card.conversation.length === 0 && <li className="text-pencil">Nothing said yet.</li>}
          </ol>
        </Row>
      ) : (
        <div className="py-2">
          <Button
            size="sm"
            variant="plain"
            disabled={busy}
            onClick={() =>
              act({ action: "show_transcript", session_id: card.session_id, student_id: card.student_id })
            }
          >
            Show what they and the agent said
          </Button>
          <span className="ml-2 text-xs text-faint">Opening a student&apos;s conversation is recorded.</span>
        </div>
      )}

    </Sheet>
  );
}
