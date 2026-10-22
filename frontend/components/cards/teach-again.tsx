"use client";

import { useId, useState } from "react";
import type { TeachAgainInfo } from "@/lib/api";
import type { Act } from "@/components/cards/parts";
import { Button } from "@/components/ui";

/** Teach the lesson that just ended to another class (or the same one again), from where
 * the teacher already is, instead of finding the lesson card first. */
export function TeachAgain({ data, act, busy }: { data: TeachAgainInfo; act: Act; busy: boolean }) {
  const id = useId();
  // Another class first: the one just taught has had it.
  const others = data.classes.filter((c) => c.id !== data.taught_class_id);
  const [klass, setKlass] = useState(others[0]?.id ?? data.classes[0]?.id ?? "");
  const chosen = data.classes.find((c) => c.id === klass);

  if (data.classes.length === 0) return null;
  return (
    <div className="mt-3 rounded-[var(--radius-control)] bg-progress-wash px-3 py-2.5">
      <p className="text-sm font-semibold text-ink">Teach it again</p>
      {data.running ? (
        <p className="mt-0.5 text-sm text-pencil">
          You have a lesson running with {data.running}. End it first, then start this one here.
        </p>
      ) : (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`${id}-class`}>
            Class to teach it to
          </label>
          <select
            id={`${id}-class`}
            value={klass}
            onChange={(e) => setKlass(e.target.value)}
            className="h-9 rounded-full border border-rule-strong bg-sheet px-3 text-sm text-ink"
          >
            {data.classes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.students})
                {c.id === data.taught_class_id ? ", just taught" : ""}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={busy || !klass}
            onClick={() => act({ action: "run", lesson_id: data.lesson_id, class_id: klass })}
          >
            {chosen ? `Start with ${chosen.label}` : "Start"}
          </Button>
        </div>
      )}
    </div>
  );
}
