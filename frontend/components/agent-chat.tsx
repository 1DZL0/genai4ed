"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";

/** A student's conversation with the class agent: the lesson itself. */

export type ChatLine = { id: string; who: "me" | "agent" | "note"; text: string };

const SPEAKER = "mb-1 text-xs font-semibold text-pencil";
const BUBBLE = "rounded-[var(--radius-sheet)] px-4 py-2.5 text-base whitespace-pre-line text-ink";

export function AgentChat({
  lines,
  pending,
  pendingText,
  onSend,
  chips,
  placeholder,
  disabled,
  disabledReason,
}: {
  lines: ChatLine[];
  pending: boolean;
  pendingText: string;
  onSend: (text: string, intent?: string) => void | Promise<void>;
  chips: { label: string; intent: string }[];
  placeholder: string;
  disabled: boolean;
  disabledReason?: string;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const blocked = disabled || pending;

  useEffect(() => {
    // A lesson being looked back on opens at its top, where the result is.
    if (!disabled) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [lines.length, pending, disabled]);

  async function send(message: string, intent?: string) {
    const trimmed = message.trim();
    if (blocked || (!trimmed && !intent)) return;
    setText("");
    await onSend(trimmed, intent);
    inputRef.current?.focus();
  }

  return (
    <div className="flex min-h-0 flex-col h-full min-h-[22rem] flex-1">
      {/* role="log" on the list itself would replace its list semantics and orphan every item, so the live region wraps the list. */}
      <div role="log" aria-live="polite" className="flex-1 overflow-y-auto px-1 py-2">
        <ol className="space-y-4">
          {lines.map((line) =>
            line.who === "note" ? (
              <li key={line.id} className="text-center text-xs text-faint">
                {line.text}
              </li>
            ) : line.who === "me" ? (
              <li key={line.id} className="flex flex-col items-end">
                <span className={SPEAKER}>You</span>
                <div className={`max-w-[85%] bg-sunken ${BUBBLE}`}>{line.text}</div>
              </li>
            ) : (
              <li key={line.id} className="flex flex-col items-start">
                <span className={SPEAKER}>Class agent</span>
                <div className={`max-w-[92%] border border-rule bg-sheet ${BUBBLE}`}>{line.text}</div>
              </li>
            ),
          )}
          {pending && (
            <li className="flex flex-col items-start">
              <span className={SPEAKER}>Class agent</span>
              <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-4 py-2.5 text-sm text-pencil">
                {pendingText}
              </div>
            </li>
          )}
        </ol>
        <div ref={endRef} />
      </div>

      <div className="border-t border-rule pt-3">
        {disabled && disabledReason && <p className="mb-2 text-sm text-pencil">{disabledReason}</p>}
        {chips.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {chips.map((chip) => (
              <button
                key={chip.label}
                type="button"
                disabled={blocked}
                onClick={() => send("", chip.intent)}
                className="rounded-full border border-rule-strong bg-sheet px-3 py-1 text-sm text-ink hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {chip.label}
              </button>
            ))}
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
          className="flex items-end gap-2"
        >
          <label htmlFor="agent-composer" className="sr-only">
            {placeholder}
          </label>
          <textarea
            id="agent-composer"
            ref={inputRef}
            rows={1}
            value={text}
            autoFocus
            disabled={disabled}
            onChange={(e) => {
              setText(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
            placeholder={placeholder}
            className="min-h-11 flex-1 resize-none rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 py-2.5 text-base text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none disabled:bg-sunken"
          />
          <Button type="submit" disabled={blocked || !text.trim()} className="h-11 shrink-0 px-5">
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}
