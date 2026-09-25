"use client";

import { useId, useState } from "react";
import type { StudentCard } from "@/lib/api";
import { Row, STATE_TEXT, STATE_WORDS, Sheet, type Act } from "@/components/cards/parts";
import { Button, Tick, clockTime } from "@/components/ui";

/* ---------- one student ---------- */

const LINK = "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink";

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

  return (
    <Sheet>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-serif text-xl font-semibold text-ink">{card.pseudonym}</h2>
        <span className={`text-sm font-semibold ${STATE_TEXT[card.state]}`}>
          {STATE_WORDS[card.state]}
        </span>
      </div>

      {(card.previous || card.next) && (
        <nav aria-label="The rest of the class" className="mt-1 flex gap-4 text-xs">
          {card.previous && (
            <button
              disabled={busy}
              onClick={() =>
                act({
                  action: "show_student",
                  session_id: card.session_id,
                  student_id: card.previous!.student_id,
                })
              }
              className={LINK}
            >
              ← {card.previous.pseudonym}
            </button>
          )}
          {card.next && (
            <button
              disabled={busy}
              onClick={() =>
                act({
                  action: "show_student",
                  session_id: card.session_id,
                  student_id: card.next!.student_id,
                })
              }
              className={`ml-auto ${LINK}`}
            >
              {card.next.pseudonym} →
            </button>
          )}
        </nav>
      )}

      <ul className="mt-1 space-y-0.5 text-sm text-ink">
        {card.summary.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {card.steps.length > 0 && (
        <Row label="Their progress">
          <ol className="space-y-1">
            {card.steps.map((s, i) => (
              <li key={`${s.name}-${i}`} className="flex items-baseline gap-2">
                {s.judgment === "met" ? <Tick className="size-4 shrink-0" /> : <span className="figures w-4 shrink-0 text-pencil">{i + 1}</span>}
                <span className={s.current ? "font-semibold text-ink" : "text-ink"}>{s.name}</span>
                {s.judgment && <span className="text-pencil">— {JUDGMENT_WORDS[s.judgment] ?? s.judgment}</span>}
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
                  {e.detail && <span className="text-pencil"> — {e.detail}</span>}
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

      {card.session_status !== "closed" && (
        <div className="mt-3 border-t border-rule pt-3">
          <label htmlFor={`${id}-guide`} className="text-xs font-bold text-pencil">
            Tell the agent how to work with {card.pseudonym}
          </label>
          <textarea
            id={`${id}-guide`}
            rows={2}
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            placeholder="e.g. Ask them to explain each step before moving on."
            className="mt-1 w-full resize-none rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-ink focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button
              size="sm"
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
              Send to the agent
            </Button>
            <label className="flex items-center gap-2 text-xs text-pencil">
              <input type="checkbox" checked={tell} onChange={(e) => setTell(e.target.checked)} />
              Show it to {card.pseudonym} too
            </label>
          </div>
        </div>
      )}
    </Sheet>
  );
}
