"use client";

import { useEffect, type ReactNode, type RefObject } from "react";
import { parseBlocks } from "@/lib/rich";

/**
 * The one conversation surface. A student in a lesson and a teacher planning one are both
 * talking to the same class agent, so both get the same room to do it in: a single column,
 * what was said, and one box to write in.
 */

/** The column the conversation and the box under it share. */
/** About 70 characters of 16px text: a line a twelve-year-old can hold in one look. */
export const COLUMN = "mx-auto w-full max-w-2xl px-4 sm:px-6";

/** One thing said. The agent's words sit on the page; yours are set apart on the right. */
export function Said({
  who,
  children,
  unsent = false,
  label,
  tint = false,
}: {
  who: "me" | "agent" | "note";
  children: ReactNode;
  unsent?: boolean;
  /** A small name above the agent's words ("Tutor" for a pupil), so a turn is told
   * apart when scrolling back. */
  label?: string;
  /** Your own words in the blue wash instead of grey: the two sides read apart at a
   * glance, the way a phone colours yours and theirs. */
  tint?: boolean;
}) {
  // `relative` keeps each screen-reader label inside its message: positioned against the page
  // instead, the labels of a long conversation stretched the whole page and made it scroll.
  // A long word (a unit name, a pasted link) wraps rather than running off the column.
  if (who === "note")
    return <p className="text-center text-xs text-faint [overflow-wrap:anywhere]">{children}</p>;
  if (who === "me") {
    return (
      <div className="flex justify-end">
        <div
          className={`relative max-w-[85%] rounded-[var(--radius-talk)] px-4 py-2 text-base [overflow-wrap:anywhere] ${
            tint ? "border border-progress/40 bg-progress-wash" : "bg-sunken"
          } ${unsent ? "text-faint" : "text-ink"}`}
        >
          <span className="sr-only">You: </span>
          {typeof children === "string" ? <Rich text={children} /> : children}
        </div>
      </div>
    );
  }
  return (
    <div className="relative text-base text-ink [overflow-wrap:anywhere]">
      {label && (
        <p aria-hidden="true" className="mb-0.5 text-xs font-semibold text-pencil">
          {label}
        </p>
      )}
      <span className="sr-only">{label ?? "Class agent"}: </span>
      {typeof children === "string" ? <Rich text={children} /> : children}
    </div>
  );
}

/** Plain text with the little structure the agent may use: lists, lines of working and
 * simple tables. */
export function Rich({ text }: { text: string }) {
  return (
    <>
      {parseBlocks(text).map((b, i) =>
        b.kind === "table" ? (
          <div key={i} className="my-2 overflow-x-auto first:mt-0 last:mb-0">
            <table className="text-sm">
              <thead>
                <tr>
                  {b.head.map((c, j) => (
                    <th key={j} className="border border-rule bg-sunken px-2 py-1 text-left font-semibold">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, k) => (
                  <tr key={k}>
                    {r.map((c, j) => (
                      <td key={j} className="figures border border-rule px-2 py-1">
                        {c}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : b.kind === "math" ? (
          <p key={i} className="figures my-2 text-lg leading-relaxed whitespace-pre-line first:mt-0 last:mb-0">
            {b.lines.join("\n")}
          </p>
        ) : b.kind === "p" ? (
          <p key={i} className="my-2 whitespace-pre-line first:mt-0 last:mb-0">
            {b.text}
          </p>
        ) : b.kind === "ol" ? (
          <ol key={i} start={b.start} className="my-2 list-decimal pl-5 first:mt-0 last:mb-0">
            {b.items.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ol>
        ) : (
          <ul key={i} className="my-2 list-disc pl-5 first:mt-0 last:mb-0">
            {b.items.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ul>
        ),
      )}
    </>
  );
}

/** The agent is working on a reply. */
export function Thinking({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2.5 text-sm text-pencil">
      <span aria-hidden className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-pulse rounded-full bg-pencil"
            style={{ animationDelay: `${i * 180}ms` }}
          />
        ))}
      </span>
      {label}
    </p>
  );
}

/** The box you write in. Enter sends; Shift and Enter starts a new line. */
export function Composer({
  id,
  label,
  value,
  onChange,
  onSubmit,
  placeholder,
  boxRef,
  canSend,
  disabled = false,
  maxLength,
  actions,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  boxRef: RefObject<HTMLTextAreaElement | null>;
  canSend: boolean;
  disabled?: boolean;
  maxLength: number;
  actions?: ReactNode;
}) {
  // Grows with what is written, up to a point, and shrinks back once it is sent. A narrower
  // window wraps the words (or the placeholder) onto more lines, so a change of width refits it.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const fit = () => {
      box.style.height = "auto";
      box.style.height = `${Math.min(box.scrollHeight, 200)}px`;
      box.style.overflowY = box.scrollHeight > 200 ? "auto" : "hidden";
    };
    fit();
    let width = box.clientWidth;
    const watch = new ResizeObserver(() => {
      if (box.clientWidth === width) return;
      width = box.clientWidth;
      fit();
    });
    watch.observe(box);
    return () => watch.disconnect();
  }, [value, boxRef]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className={`composer relative rounded-[var(--radius-talk)] border px-3 pt-2 pb-2 ${
        disabled ? "border-rule bg-sunken" : "border-rule-strong bg-sheet"
      }`}
    >
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <textarea
        id={id}
        ref={boxRef}
        rows={1}
        value={value}
        autoFocus
        disabled={disabled}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder={placeholder}
        className="block w-full resize-none bg-transparent px-2 py-2 text-base text-ink placeholder:text-faint focus:outline-none disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between gap-3 pl-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm">{actions}</div>
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send"
          className="flex h-9 shrink-0 items-center justify-center rounded-full bg-ink px-4 text-sm font-semibold text-white transition-colors hover:bg-ink-hover disabled:cursor-not-allowed disabled:bg-rule-strong sm:size-9 sm:px-0"
        >
          {/* A word on a phone, where the circle alone is small under a thumb. */}
          <span className="sm:hidden">Send</span>
          <svg
            viewBox="0 0 20 20"
            aria-hidden
            className="hidden size-4 sm:block"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" />
          </svg>
        </button>
      </div>
    </form>
  );
}
