"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, ErrorNote } from "@/components/ui";

/**
 * A conversation with the class agent. Used by the teacher to shape a lesson
 * and ask about the class, and by a student as the lesson itself.
 */

export type ChatLine = {
  id: string;
  who: "me" | "agent" | "note";
  text: string;
  /** Small text under the words: files attached, what the agent changed. */
  footnote?: ReactNode;
};

export type Chip = { label: string; send?: string; intent?: string; fill?: string };

export function AgentChat({
  lines,
  pending = false,
  pendingText = "The agent is thinking…",
  onSend,
  onFiles,
  chips = [],
  placeholder = "Write to the agent",
  disabled = false,
  disabledReason,
  agentName = "Class agent",
  meName = "You",
  empty,
  error,
  className = "",
  autoFocus = false,
}: {
  lines: ChatLine[];
  pending?: boolean;
  pendingText?: string;
  onSend: (text: string, files: File[], intent?: string) => void | Promise<void>;
  onFiles?: boolean;
  chips?: Chip[];
  placeholder?: string;
  disabled?: boolean;
  disabledReason?: string;
  agentName?: string;
  meName?: string;
  empty?: ReactNode;
  error?: string | null;
  className?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const count = lines.length;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [count, pending]);

  const blocked = disabled || pending;

  async function send(message: string, intent?: string) {
    const trimmed = message.trim();
    if (blocked || (!trimmed && files.length === 0 && !intent)) return;
    const attached = files;
    setText("");
    setFiles([]);
    await onSend(trimmed, attached, intent);
    inputRef.current?.focus();
  }

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      <ol role="log" aria-live="polite" className="flex-1 space-y-4 overflow-y-auto px-1 py-2">
        {count === 0 && !pending && empty && <li className="text-sm text-pencil">{empty}</li>}
        {lines.map((line) =>
          line.who === "note" ? (
            <li key={line.id} className="text-center text-xs text-faint">
              {line.text}
            </li>
          ) : line.who === "me" ? (
            <li key={line.id} className="flex flex-col items-end">
              <span className="mb-1 text-xs font-semibold text-pencil">{meName}</span>
              <div className="max-w-[85%] rounded-[var(--radius-sheet)] bg-sunken px-4 py-2.5 text-base whitespace-pre-line text-ink">
                {line.text}
              </div>
              {line.footnote && <div className="mt-1 text-xs text-faint">{line.footnote}</div>}
            </li>
          ) : (
            <li key={line.id} className="flex flex-col items-start">
              <span className="mb-1 text-xs font-semibold text-pencil">{agentName}</span>
              <div className="max-w-[92%] rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-2.5 text-base whitespace-pre-line text-ink">
                {line.text}
              </div>
              {line.footnote && <div className="mt-1 text-xs text-faint">{line.footnote}</div>}
            </li>
          ),
        )}
        {pending && (
          <li className="flex flex-col items-start">
            <span className="mb-1 text-xs font-semibold text-pencil">{agentName}</span>
            <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-4 py-2.5 text-sm text-pencil">
              {pendingText}
            </div>
          </li>
        )}
        <div ref={endRef} />
      </ol>

      <div className="border-t border-rule pt-3">
        {error && (
          <div className="mb-2">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        {disabled && disabledReason && (
          <p className="mb-2 text-sm text-pencil">{disabledReason}</p>
        )}
        {chips.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {chips.map((chip) => (
              <button
                key={chip.label}
                type="button"
                disabled={blocked}
                onClick={() => {
                  if (chip.fill !== undefined) {
                    setText(chip.fill);
                    inputRef.current?.focus();
                  } else {
                    send(chip.send ?? chip.label, chip.intent);
                  }
                }}
                className="rounded-full border border-rule-strong bg-sheet px-3 py-1 text-sm text-ink hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {chip.label}
              </button>
            ))}
          </div>
        )}
        {files.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-2" aria-label="Files to send">
            {files.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center gap-2 rounded-full bg-sunken px-3 py-1 text-xs text-ink"
              >
                {f.name}
                <button
                  type="button"
                  aria-label={`Remove ${f.name}`}
                  onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
                  className="text-pencil hover:text-ink"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
          className="flex items-end gap-2"
        >
          {onFiles && (
            <>
              <input
                ref={fileRef}
                type="file"
                multiple
                accept=".pdf,.docx,.pptx,.txt,.md,image/png,image/jpeg,image/webp,image/gif"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []);
                  setFiles((all) => [...all, ...picked].slice(0, 10));
                  e.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="quiet"
                disabled={blocked}
                onClick={() => fileRef.current?.click()}
                className="h-11 shrink-0"
                aria-label="Attach teaching material"
              >
                Attach
              </Button>
            </>
          )}
          <label htmlFor="agent-composer" className="sr-only">
            {placeholder}
          </label>
          <textarea
            id="agent-composer"
            ref={inputRef}
            rows={1}
            value={text}
            autoFocus={autoFocus}
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
          <Button
            type="submit"
            disabled={blocked || (!text.trim() && files.length === 0)}
            className="h-11 shrink-0 px-5"
          >
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}
