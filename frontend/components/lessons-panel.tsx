"use client";

import { useEffect, useId, useRef, useState } from "react";
import useSWR from "swr";
import { threadApi, type LessonsCard } from "@/lib/api";
import { Wordmark } from "@/components/app-header";
import { LessonRow, type Act } from "@/components/cards";
import { Button, Skeleton } from "@/components/ui";

type Listed = LessonsCard["lessons"][number];

/** Your lessons by unit, down the side while you plan. Pressing one shows it beside the conversation. */
export function LessonsSide({
  act,
  busy,
  current,
  from,
}: {
  act: Act;
  busy: boolean;
  current: string | null;
  /** The width it appears from: beside a card it needs a wide screen, or the talk gets squeezed. */
  from: "lg:flex" | "2xl:flex";
}) {
  const { data } = useSWR<LessonsCard>("thread-lessons", threadApi.lessons, { refreshInterval: 15000 });
  const lessons = data?.lessons ?? [];
  // Newest first from the server; inside a unit, first lesson first.
  const units = new Map<string, Listed[]>();
  const single: Listed[] = [];
  for (const l of lessons) {
    if (l.unit) units.set(l.unit, [l, ...(units.get(l.unit) ?? [])]);
    else single.push(l);
  }

  return (
    <aside
      aria-label="Your lessons"
      className={`no-print hidden w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r border-rule py-4 pr-5 ${from}`}
    >
      <Wordmark href="/teacher" />
      {data && lessons.length === 0 && (
        <p className="text-sm text-pencil">Nothing yet. Describe a lesson and the agent will draft it.</p>
      )}
      {units.size > 0 && (
        <div>
          <h2 className="mb-1 text-xs font-bold text-pencil">Units</h2>
          <ul className="space-y-2">
            {[...units].map(([name, list]) => (
              <li key={name} className="rounded-[10px] bg-sunken px-1.5 pt-1.5 pb-1">
                <p className="px-2 text-[15px] font-bold text-ink">{name}</p>
                <ol>
                  {list.map((l, i) => (
                    <SideRow key={l.lesson_id} lesson={l} n={i + 1} act={act} busy={busy} current={current} />
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        </div>
      )}
      {single.length > 0 && (
        <div>
          <h2 className="mb-1 text-xs font-bold text-pencil">{units.size > 0 ? "Single lessons" : "Lessons"}</h2>
          <ul>
            {single.map((l) => (
              <SideRow key={l.lesson_id} lesson={l} act={act} busy={busy} current={current} />
            ))}
          </ul>
        </div>
      )}
      <Button size="sm" variant="quiet" className="self-start" disabled={busy} onClick={() => act({ action: "new_lesson" })}>
        New lesson
      </Button>
    </aside>
  );
}

function SideRow({ lesson, n, act, busy, current }: { lesson: Listed; n?: number; act: Act; busy: boolean; current: string | null }) {
  const now = lesson.lesson_id === current;
  const [word, tone] = lesson.live
    ? ["Running", "text-tick"]
    : !lesson.ready
      ? ["Unfinished", "text-amber"]
      : lesson.last_run
        ? ["Taught", "text-tick"]
        : lesson.status === "active"
          ? ["Ready", "text-ink"]
          : ["Draft", "text-amber"];
  const [removing, setRemoving] = useState(false);
  if (removing)
    return (
      <li className="flex flex-wrap items-center gap-2 rounded-[8px] bg-sheet px-2 py-1.5 text-sm text-ink shadow-[inset_0_0_0_1px_var(--rule-strong)]">
        <span className="min-w-0 flex-1">
          {lesson.live
            ? "Running now: removing it ends it for everyone."
            : lesson.last_run
              ? "Remove it? Lessons already taught are kept."
              : "Remove it?"}
        </span>
        <Button
          size="sm"
          variant="red"
          disabled={busy}
          onClick={() => act({ action: "delete_lesson", lesson_id: lesson.lesson_id })}
        >
          Remove
        </Button>
        <Button size="sm" variant="plain" onClick={() => setRemoving(false)}>
          Keep
        </Button>
      </li>
    );
  return (
    <li className="flex items-center gap-1">
      <button
        type="button"
        disabled={busy}
        aria-current={now ? "true" : undefined}
        onClick={() => act({ action: "show_lesson", lesson_id: lesson.lesson_id })}
        className={`flex min-w-0 flex-1 items-baseline justify-between gap-2 rounded-[8px] px-2 py-1.5 text-left text-[15px] text-ink hover:bg-sunken disabled:opacity-50 ${
          now ? "bg-sheet font-semibold shadow-[inset_0_0_0_1px_var(--rule-strong)]" : ""
        }`}
      >
        <span className="min-w-0 truncate">
          {n ? `${n}. ` : ""}
          {lesson.title}
        </span>
        <span className={`shrink-0 text-xs font-semibold ${tone}`}>{word}</span>
      </button>
      <button
        type="button"
        disabled={busy}
        aria-label={`Remove ${lesson.title}`}
        title="Remove this lesson"
        onClick={() => setRemoving(true)}
        className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-red-pen hover:bg-red-pen-wash disabled:opacity-50"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          className="size-[18px] fill-none stroke-current"
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6h12M8 6V4.5h4V6M6.5 6l.6 9h5.8l.6-9M8.5 9v4M11.5 9v4" />
        </svg>
      </button>
    </li>
  );
}

/** Your lessons, over the thread rather than in it: browsing is not a turn, so the conversation stays put. */
export function LessonsPanel({ onClose, act, busy }: { onClose: () => void; act: Act; busy: boolean }) {
  // Mounted only while open, so the list is read fresh each time.
  const { data, isLoading } = useSWR<LessonsCard>("thread-lessons", threadApi.lessons);
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Keyboard users land in the panel when it opens and go back where they were when it closes.
    const cameFrom = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      cameFrom?.focus?.();
    };
  }, [onClose]);

  const lessons = data?.lessons ?? [];

  return (
    <>
      {/* Clicking away closes it; hidden from screen readers, which have Escape and the Close button. */}
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40 bg-ink/15" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="fixed top-0 right-0 bottom-0 z-50 flex w-full max-w-sm flex-col border-l border-rule bg-sheet"
      >
        <header className="flex items-center justify-between gap-3 border-b border-rule px-5 py-3">
          <h2 id={titleId} className="text-base font-bold text-ink">
            Your lessons
          </h2>
          <span className="flex items-center gap-3">
            <Button
              size="sm"
              variant="quiet"
              disabled={busy}
              onClick={async () => {
                await act({ action: "new_lesson" });
                onClose();
              }}
            >
              New lesson
            </Button>
            <Button ref={closeRef} variant="plain" size="sm" onClick={onClose}>
              Close
            </Button>
          </span>
        </header>

        <div className="flex-1 overflow-y-auto px-5">
          {isLoading && !data && (
            <div className="py-4">
              <Skeleton label="Loading your lessons" rows={3} />
            </div>
          )}
          {data && lessons.length === 0 && (
            <p className="py-4 text-sm text-pencil">
              Nothing yet. Describe a lesson and the agent will draft it.
            </p>
          )}
          <ul role="list" className="divide-y divide-rule">
            {lessons.map((l) => (
              <LessonRow
                key={l.lesson_id}
                lesson={l}
                classes={data?.classes ?? []}
                act={act}
                busy={busy}
                after={onClose}
              />
            ))}
          </ul>
        </div>
      </aside>
    </>
  );
}
