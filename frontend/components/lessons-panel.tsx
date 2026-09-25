"use client";

import { useEffect, useId, useRef } from "react";
import useSWR from "swr";
import { threadApi, type LessonsCard } from "@/lib/api";
import { LessonRow, type Act } from "@/components/cards";
import { Button, Skeleton } from "@/components/ui";

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
