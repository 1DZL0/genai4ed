"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { COLUMN, Composer, Said, Thinking } from "@/components/chat";

/** A student's conversation with the class agent: the lesson itself. */

export type ChatLine = { id: string; who: "me" | "agent" | "note"; text: string };

export function AgentChat({
  lines,
  pending,
  pendingText,
  onSend,
  chips,
  placeholder,
  disabled,
  above,
  task,
  notice,
  actions,
  footnote,
}: {
  lines: ChatLine[];
  pending: boolean;
  pendingText: string;
  onSend: (text: string, intent?: string) => void | Promise<void>;
  chips: { label: string; intent: string }[];
  placeholder: string;
  disabled: boolean;
  /** Shown before the conversation: a result, once there is one. */
  above?: ReactNode;
  /** The question on the table, kept in sight while they write. */
  task?: string | null;
  /** Why the box is closed, or that the activity is done. */
  notice?: ReactNode;
  actions?: ReactNode;
  footnote?: string;
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
    <div className="flex min-h-0 flex-1 flex-col">
      {/* role="log" on the list itself would replace its list semantics and orphan every item, so the live region wraps the list. */}
      <div role="log" aria-live="polite" className="min-h-0 flex-1 overflow-y-auto">
        <div className={`${COLUMN} py-6`}>
          {above}
          <ol className="space-y-6">
            {lines.map((line) => (
              <li key={line.id}>
                <Said who={line.who} unsent={line.id === "pending"}>
                  {line.text}
                </Said>
              </li>
            ))}
            {pending && (
              <li>
                <Thinking label={pendingText} />
              </li>
            )}
          </ol>
          <div ref={endRef} />
        </div>
      </div>

      <div className={`${COLUMN} shrink-0 pt-2 pb-3`}>
        {task && (
          <p className="mb-2 text-sm text-pencil">
            Working on <span className="font-semibold text-ink">{task}</span>
          </p>
        )}
        {notice && <div className="mb-2 text-sm">{notice}</div>}
        {chips.length > 0 && (
          /* One row that scrolls sideways on a phone, so the talk keeps its room. */
          <div className="no-scrollbar mb-2 flex gap-2 overflow-x-auto sm:flex-wrap sm:overflow-visible">
            {chips.map((chip) => (
              <button
                key={chip.label}
                type="button"
                disabled={blocked}
                onClick={() => send("", chip.intent)}
                className="shrink-0 rounded-full border border-rule bg-sheet px-3 py-1 text-sm whitespace-nowrap text-pencil hover:border-ink hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {chip.label}
              </button>
            ))}
          </div>
        )}
        <Composer
          id="agent-composer"
          label={placeholder}
          value={text}
          onChange={setText}
          onSubmit={() => send(text)}
          placeholder={placeholder}
          boxRef={inputRef}
          disabled={disabled}
          maxLength={2000}
          canSend={!blocked && Boolean(text.trim())}
          actions={actions}
        />
        {footnote && <p className="mt-2 text-center text-xs text-faint">{footnote}</p>}
      </div>
    </div>
  );
}
