"use client";

import { useEffect, type ReactNode, type RefObject } from "react";
import { parseBlocks } from "@/lib/rich";
import { subjectCover } from "@/components/ui";

/**
 * The one conversation surface. A student in a lesson and a teacher planning one are both
 * talking to the same class agent, so both get the same room to do it in: a single column,
 * what was said, and one box to write in.
 */

/** The column the conversation and the box under it share. */
/** About 70 characters of 16px text: a line a twelve-year-old can hold in one look. */
export const COLUMN = "mx-auto w-full max-w-2xl px-4 sm:px-6";

/** One thing said. The agent's words sit on the page; yours are set apart on the right. In the
 * pupil's chat both sides get a speech bubble and a face, so who is talking is clear at a glance. */
export function Said({
  who,
  children,
  unsent = false,
  label,
  tint = false,
  pupil = false,
  subject,
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
  /** The pupil's warmer look: the tutor in a white bubble with a pencil beside it, you in solid
   * blue with a face of your own. The teacher's planning chat does not use it. */
  pupil?: boolean;
  /** The lesson's subject, which colours the tutor's pencil like an exercise-book cover. */
  subject?: string;
}) {
  // `relative` keeps each screen-reader label inside its message: positioned against the page
  // instead, the labels of a long conversation stretched the whole page and made it scroll.
  // A long word (a unit name, a pasted link) wraps rather than running off the column.
  if (who === "note")
    return <p className="text-center text-xs text-faint [overflow-wrap:anywhere]">{children}</p>;
  const words = typeof children === "string" ? <Rich text={children} /> : children;
  if (who === "me") {
    if (pupil) {
      return (
        <div className="flex items-end justify-end gap-2">
          <div
            className={`relative max-w-[85%] rounded-[var(--radius-talk)] bg-progress px-4 py-2 text-base text-white [overflow-wrap:anywhere] ${
              unsent ? "opacity-70" : ""
            }`}
          >
            <span className="sr-only">You: </span>
            {words}
          </div>
          <PupilFace />
        </div>
      );
    }
    return (
      <div className="flex justify-end">
        <div
          className={`relative max-w-[85%] rounded-[var(--radius-talk)] px-4 py-2 text-base [overflow-wrap:anywhere] ${
            tint ? "border border-progress/40 bg-progress-wash" : "bg-sunken"
          } ${unsent ? "text-faint" : "text-ink"}`}
        >
          <span className="sr-only">You: </span>
          {words}
        </div>
      </div>
    );
  }
  if (pupil) {
    return (
      <div className="flex items-end gap-2">
        <TutorFace subject={subject} />
        <div className="min-w-0 max-w-[85%]">
          {label && (
            <p aria-hidden="true" className="mb-0.5 pl-1 text-xs font-semibold text-pencil">
              {label}
            </p>
          )}
          <div className="relative rounded-[var(--radius-talk)] border border-rule bg-sheet px-4 py-2 text-base text-ink [overflow-wrap:anywhere]">
            <span className="sr-only">{label ?? "Class agent"}: </span>
            {words}
          </div>
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
      {words}
    </div>
  );
}

/** The tutor's face: a pencil, in the colour of the lesson's exercise-book cover. It is a
 * tool, not a person, which is the honest thing to show a child talking to an AI. Decorative:
 * the words beside it already say who is speaking. The subject wash falls back to the plain
 * sunken grey where color-mix is not understood. */
export function TutorFace({ subject = "" }: { subject?: string }) {
  const { colour } = subjectCover(subject);
  return (
    <span
      aria-hidden="true"
      className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sunken"
      style={{ color: colour, backgroundColor: `color-mix(in srgb, ${colour} 14%, white)` }}
    >
      <svg
        viewBox="0 0 24 24"
        className="size-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
      </svg>
    </span>
  );
}

/** The pupil's face: a plain silhouette, since this one really is a person. */
function PupilFace() {
  return (
    <span
      aria-hidden="true"
      className="flex size-7 shrink-0 items-center justify-center rounded-full bg-progress-wash text-progress"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="currentColor">
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21a8 8 0 0 1 16 0Z" />
      </svg>
    </span>
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

/** The agent is working on a reply. In the pupil's chat the dots sit beside the tutor's
 * pencil, so the wait looks like the tutor thinking rather than a loose spinner. */
export function Thinking({
  label,
  pupil = false,
  subject,
}: {
  label: string;
  pupil?: boolean;
  subject?: string;
}) {
  const dots = (
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
  if (!pupil) return dots;
  return (
    <div className="flex items-center gap-2">
      <TutorFace subject={subject} />
      {dots}
    </div>
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
