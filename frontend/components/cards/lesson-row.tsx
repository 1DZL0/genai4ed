"use client";

import { useId, useState } from "react";
import type { ClassOut, LessonsCard, ThreadAction } from "@/lib/api";
import { Sheet, type Act } from "@/components/cards/parts";
import { Button, SubjectName } from "@/components/ui";
import { STATUS_PILL, canStart, lessonStatus, removeWords } from "@/components/cards/lesson-status";

/* ---------- every lesson ---------- */

export function Lessons({ card, act, busy }: { card: LessonsCard; act: Act; busy: boolean }) {
  return (
    <Sheet>
      <div className="flex items-baseline justify-between gap-3 border-b border-rule pb-2">
        <h2 className="text-base font-bold text-ink">Your lessons</h2>
        <Button size="sm" variant="quiet" disabled={busy} onClick={() => act({ action: "new_lesson" })}>
          New lesson
        </Button>
      </div>
      {card.lessons.length === 0 ? (
        <p className="pt-3 text-sm text-pencil">
          Nothing yet. Describe a lesson and the agent will draft it.
        </p>
      ) : (
        <ul role="list" className="divide-y divide-rule">
          {card.lessons.map((l) => (
            <LessonRow key={l.lesson_id} lesson={l} classes={card.classes} act={act} busy={busy} />
          ))}
        </ul>
      )}
    </Sheet>
  );
}

/** One lesson in a list, with everything a teacher does to it. The card and the panel share it, so they behave the same. */
export function LessonRow({
  lesson,
  classes,
  act,
  busy,
  after,
}: {
  lesson: LessonsCard["lessons"][number];
  classes: ClassOut[];
  act: Act;
  busy: boolean;
  after?: () => void;
}) {
  const id = useId();
  const [klass, setKlass] = useState("");
  const [starting, setStarting] = useState(false);
  const [removing, setRemoving] = useState(false);
  // A pill like every other button on a card, so it reads as one.
  const pill =
    "inline-flex h-8 items-center rounded-full border border-rule-strong bg-sheet px-3 text-sm font-semibold text-ink hover:border-ink disabled:opacity-40";

  async function run(action: ThreadAction) {
    await act(action);
    after?.();
  }

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <SubjectName subject={lesson.subject} />
        <span className={`${STATUS_PILL} ${lessonStatus(lesson)[1]}`}>
          {lessonStatus(lesson)[0]}
        </span>
      </div>
      <p className="font-serif text-lg leading-snug font-semibold text-ink [overflow-wrap:anywhere]">
        {lesson.title}
      </p>
      <p className="text-xs text-pencil [overflow-wrap:anywhere]">
        {lesson.unit && `${lesson.unit} · `}
        {lesson.ready
          ? `${lesson.steps} steps, ${lesson.duration_minutes} min`
          : "Not finished: tell the agent what it still needs"}
        {lesson.live && ` · running with ${lesson.live.class_label}`}
      </p>

      {starting ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
          <label htmlFor={`${id}-class`} className="text-pencil">
            with
          </label>
          <select
            id={`${id}-class`}
            value={klass}
            onChange={(e) => setKlass(e.target.value)}
            className="h-8 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink"
          >
            <option value="">Choose a class</option>
            {classes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.students})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={busy || !klass}
            onClick={() => run({ action: "run", lesson_id: lesson.lesson_id, class_id: klass })}
          >
            Start
          </Button>
          <Button size="sm" variant="plain" onClick={() => setStarting(false)}>
            Not now
          </Button>
        </div>
      ) : removing ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink">
          {removeWords(lesson)}
          <Button
            size="sm"
            variant="red"
            disabled={busy}
            onClick={() => run({ action: "delete_lesson", lesson_id: lesson.lesson_id })}
          >
            Remove
          </Button>
          <Button size="sm" variant="plain" onClick={() => setRemoving(false)}>
            Keep it
          </Button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {lesson.live ? (
            <Button
              size="sm"
              variant="pillDark"
              disabled={busy}
              onClick={() => run({ action: "show_class", session_id: lesson.live!.session_id })}
            >
              See the class
            </Button>
          ) : (
            <Button
              size="sm"
              variant="pillDark"
              disabled={busy || !canStart(lesson)}
              onClick={() => setStarting(true)}
              title={
                !canStart(lesson)
                  ? lesson.ready
                    ? "Approve it first"
                    : "Finish it and approve it first"
                  : lesson.status === "draft"
                    ? "Starts the approved version; your change is not approved yet"
                    : undefined
              }
            >
              Start lesson
            </Button>
          )}
          <Button
            size="sm"
            variant="pill"
            disabled={busy}
            onClick={() => run({ action: "focus_lesson", lesson_id: lesson.lesson_id })}
          >
            Let&apos;s work on this
          </Button>
          {lesson.last_run && (
            <Button
              size="sm"
              variant="pill"
              disabled={busy}
              onClick={() => run({ action: "show_outcomes", session_id: lesson.last_run!.session_id })}
            >
              How it went
              {lesson.last_run.outcomes_to_confirm > 0 && (
                <span className="rounded-full bg-amber-wash px-1.5 text-xs text-amber">
                  {lesson.last_run.outcomes_to_confirm} to confirm
                </span>
              )}
            </Button>
          )}
          <button disabled={busy} onClick={() => setRemoving(true)} className={`${pill} ml-auto`}>
            Remove
          </button>
        </div>
      )}
    </li>
  );
}
