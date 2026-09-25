"use client";

import { useId, useState } from "react";
import type { ClassOut, LessonsCard, ThreadAction } from "@/lib/api";
import { Sheet, type Act } from "@/components/cards/parts";
import { Button, SubjectName } from "@/components/ui";

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
  // Big enough to tap: a link's text, a button's height.
  const link =
    "py-1.5 text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink disabled:opacity-40";

  async function run(action: ThreadAction) {
    await act(action);
    after?.();
  }

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <SubjectName subject={lesson.subject} />
        <span
          className={`text-xs font-semibold ${lesson.ready && lesson.status === "active" ? "text-tick" : "text-amber"}`}
        >
          {!lesson.ready ? "Unfinished" : lesson.status === "active" ? "Ready" : "Draft"}
        </span>
      </div>
      <p className="font-serif text-lg leading-snug font-semibold text-ink">{lesson.title}</p>
      <p className="text-xs text-pencil">
        {lesson.ready
          ? `${lesson.steps} steps, ${lesson.duration_minutes} min`
          : "Not finished - tell the agent what it still needs"}
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
          Remove it?
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
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0 text-sm">
          <button
            disabled={busy}
            onClick={() => run({ action: "focus_lesson", lesson_id: lesson.lesson_id })}
            className="py-1.5 font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink disabled:opacity-40"
          >
            Let&apos;s work on this
          </button>
          {lesson.live ? (
            <button
              disabled={busy}
              onClick={() => run({ action: "show_class", session_id: lesson.live!.session_id })}
              className={link}
            >
              The class
            </button>
          ) : (
            <button
              disabled={busy || !lesson.ready || lesson.status !== "active"}
              onClick={() => setStarting(true)}
              title={
                !lesson.ready
                  ? "It needs finishing first"
                  : lesson.status !== "active"
                    ? "Approve it first"
                    : undefined
              }
              className={link}
            >
              Start lesson
            </button>
          )}
          {lesson.last_run && (
            <button
              disabled={busy}
              onClick={() => run({ action: "show_outcomes", session_id: lesson.last_run!.session_id })}
              className={link}
            >
              Review
              {lesson.last_run.outcomes_to_confirm > 0 &&
                ` (${lesson.last_run.outcomes_to_confirm} to confirm)`}
            </button>
          )}
          <button disabled={busy} onClick={() => setRemoving(true)} className={`${link} ml-auto`}>
            Remove
          </button>
        </div>
      )}
    </li>
  );
}
