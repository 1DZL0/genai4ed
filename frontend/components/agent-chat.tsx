"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { COLUMN, Composer, Said, Thinking } from "@/components/chat";

/** A student's conversation with the class agent: the lesson itself. */

export type ChatLine = {
  id: string;
  who: "me" | "agent" | "note";
  text: string;
  /** The student's tap on this reply, when it is the agent's. */
  helped?: boolean | null;
};

// The most a student may send at once, as the server holds it (SayIn in routers/learn.py).
const MAX_CHARS = 2000;

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
  onRate,
  symbols = false,
  topKey,
}: {
  lines: ChatLine[];
  pending: boolean;
  pendingText: string;
  /** Resolves false when the message did not go through, so the box gives it back. */
  onSend: (text: string, intent?: string) => void | boolean | Promise<void | boolean>;
  chips: { label: string; intent: string; disabled?: boolean }[];
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
  /** The student's tap on an agent reply, when the page records it. */
  onRate?: (lineId: string, helped: boolean) => void;
  /** A row of maths symbols to tap into the box, behind a small button: not everyone knows / is divide. */
  symbols?: boolean;
  /** Changes when something new is put above the conversation (the lesson ending, a mark):
   * the view goes to the top, where it is, instead of staying at the last line. */
  topKey?: string;
}) {
  const [text, setText] = useState("");
  const [keys, setKeys] = useState(false);

  /** Puts a symbol where the caret is and keeps the caret after it, within the box's limit. */
  function insert(symbol: string) {
    const box = inputRef.current;
    const start = box?.selectionStart ?? text.length;
    const end = box?.selectionEnd ?? text.length;
    const next = text.slice(0, start) + symbol + text.slice(end);
    if (next.length > MAX_CHARS) return;
    setText(next);
    requestAnimationFrame(() => {
      box?.focus();
      box?.setSelectionRange(start + symbol.length, start + symbol.length);
    });
  }
  const endRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const blocked = disabled || pending;

  useEffect(() => {
    // A lesson being looked back on opens at its top, where the result is.
    if (!disabled) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [lines.length, pending, disabled]);

  useEffect(() => {
    if (topKey) logRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [topKey]);

  async function send(message: string, intent?: string) {
    const trimmed = message.trim();
    if (blocked || (!trimmed && !intent)) return;
    // A help button sends only itself: what they had typed stays in the box.
    if (trimmed) setText("");
    // A message that did not go through comes back to the box, so nothing they wrote is lost.
    if ((await onSend(trimmed, intent)) === false && trimmed) setText((now) => now || message);
    inputRef.current?.focus();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* role="log" on the list itself would replace its list semantics and orphan every item, so the live region wraps the list. */}
      <div ref={logRef} role="log" aria-live="polite" className="min-h-0 flex-1 overflow-y-auto">
        <div className={`${COLUMN} py-6`}>
          {above}
          <ol className="space-y-6">
            {lines.map((line) => (
              <li key={line.id}>
                <Said who={line.who} unsent={line.id === "pending"}>
                  {line.text}
                </Said>
                {onRate && line.who === "agent" && <Rate line={line} onRate={onRate} />}
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
                disabled={blocked || chip.disabled}
                onClick={() => send("", chip.intent)}
                className="shrink-0 rounded-full border border-rule bg-sheet px-3 py-1 text-sm whitespace-nowrap text-pencil hover:border-ink hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {chip.label}
              </button>
            ))}
          </div>
        )}
        {symbols && keys && (
          <div role="group" aria-label="Maths symbols" className="mb-2 flex flex-wrap gap-1.5">
            {SYMBOLS.map((k) => (
              <button
                key={k.sym}
                type="button"
                disabled={disabled}
                onClick={() => insert(k.sym)}
                aria-label={`${k.word}, ${k.sym}`}
                className="flex min-w-11 flex-col items-center rounded-[var(--radius-control)] border border-rule bg-sheet px-2 py-1 hover:border-ink disabled:opacity-50"
              >
                <span className="text-lg leading-tight text-ink">{k.sym}</span>
                <span className="text-[10px] leading-tight text-pencil">{k.word}</span>
              </button>
            ))}
            <p className="basis-full text-xs text-pencil">
              Tap one to put it where you are typing. Words work too: &ldquo;3 divided by 4&rdquo;,
              &ldquo;x squared&rdquo;.
            </p>
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
          maxLength={MAX_CHARS}
          canSend={!blocked && Boolean(text.trim())}
          actions={
            <>
              {symbols && (
                <button
                  type="button"
                  aria-expanded={keys}
                  onClick={() => setKeys(!keys)}
                  className="text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink"
                >
                  {keys ? "Hide symbols" : "Maths symbols"}
                </button>
              )}
              {actions}
            </>
          }
        />
        {footnote && <p className="mt-2 text-center text-xs text-faint">{footnote}</p>}
      </div>
    </div>
  );
}

/** The symbols a keyboard hides, each with its word, so ÷ reads as divide and / as a fraction. */
const SYMBOLS: { sym: string; word: string }[] = [
  { sym: "÷", word: "divide" },
  { sym: "×", word: "times" },
  { sym: "/", word: "fraction" },
  { sym: "=", word: "equals" },
  { sym: "≠", word: "not equal" },
  { sym: "<", word: "less than" },
  { sym: ">", word: "more than" },
  { sym: "≤", word: "at most" },
  { sym: "≥", word: "at least" },
  { sym: "²", word: "squared" },
  { sym: "³", word: "cubed" },
  { sym: "√", word: "root" },
  { sym: "π", word: "pi" },
  { sym: "°", word: "degrees" },
  { sym: "%", word: "per cent" },
];

/** One tap after an agent reply: it helped, or not really. A research signal, kept beside the reply. */
function Rate({
  line,
  onRate,
}: {
  line: ChatLine;
  onRate: (lineId: string, helped: boolean) => void;
}) {
  const base = "rounded-full border px-2.5 py-0.5 text-xs transition-colors";
  const on = "border-ink bg-ink text-white";
  const off = "border-rule text-pencil hover:border-ink hover:text-ink";
  return (
    <div className="mt-1.5 flex items-center gap-1.5" role="group" aria-label="Did that help?">
      <button
        type="button"
        aria-pressed={line.helped === true}
        onClick={() => onRate(line.id, true)}
        className={`${base} ${line.helped === true ? on : off}`}
      >
        That helped
      </button>
      <button
        type="button"
        aria-pressed={line.helped === false}
        onClick={() => onRate(line.id, false)}
        className={`${base} ${line.helped === false ? on : off}`}
      >
        Not really
      </button>
    </div>
  );
}
