"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, researchApi, type MemorySettings } from "@/lib/api";
import { Button, ErrorNote, Notice, Panel } from "@/components/ui";

const SELECT =
  "h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink disabled:text-faint";
const DAYS = [1, 7, 30];
const LINES = [3, 7, 10];

/** The choices of a list, with the one already saved among them when it is none of the usual. */
function withSaved(usual: number[], saved: number | null): number[] {
  return saved && !usual.includes(saved) ? [...usual, saved].sort((a, b) => a - b) : usual;
}

/** What the tutor is told about a student's earlier lessons, set by the teacher for every
 * lesson of theirs, and the deleting of it. Hiding removes nothing; deleting asks first. */
export function MemoryPanel({ researchKey }: { researchKey: string }) {
  const { data, error: unread, mutate } = useSWR(["research-memory", researchKey], () =>
    researchApi.memory(researchKey),
  );
  const [draft, setDraft] = useState<MemorySettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  if (unread) return <ErrorNote>{(unread as ApiError).message}</ErrorNote>;
  if (!data) return null;

  const saved = data.settings;
  // The deeper question and the tutor adapting are stored with these but are not set here, so
  // what is sent from here is always the stored value: saving never changes them.
  const now = {
    ...(draft ?? saved),
    harder_questions: saved.harder_questions,
    adapt_to_student: saved.adapt_to_student,
  };
  const changed = (Object.keys(saved) as (keyof MemorySettings)[]).some((k) => now[k] !== saved[k]);
  const set = (change: Partial<MemorySettings>) => {
    setDraft({ ...now, ...change });
    setDone(null);
  };

  async function tryTo(work: () => Promise<Awaited<ReturnType<typeof researchApi.memory>>>, said: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await mutate(await work(), { revalidate: false });
      setDraft(null);
      setDone(said);
    } catch (e) {
      setError((e as ApiError).message);
    }
    setBusy(false);
    setAsking(false);
  }

  const students = data.students === 1 ? "1 of your students" : `${data.students} of your students`;

  return (
    <Panel
      title="Memory between lessons"
      description="What the tutor is told about a student's earlier lessons, from its next reply."
    >
      <div className="grid gap-x-8 gap-y-4 text-sm text-ink md:grid-cols-2">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5 shrink-0"
            checked={now.remember}
            onChange={(e) => set({ remember: e.target.checked })}
          />
          <span>
            <span className="font-semibold">Remember students between lessons</span>
            <span className="block text-xs text-pencil">
              Off: the tutor starts each lesson knowing nothing from earlier ones. Nothing is removed.
            </span>
          </span>
        </label>

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5 shrink-0"
            checked={now.written_lines}
            disabled={!now.remember}
            onChange={(e) => set({ written_lines: e.target.checked })}
          />
          <span>
            <span className="font-semibold">Include the notes written at a lesson review</span>
            <span className="block text-xs text-pencil">
              Sentences the AI writes about how a student learns. Off: the tutor is told only what
              was counted, such as tries, hints and steps right.
            </span>
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-semibold">Forget lessons older than</span>
          <select
            className={`${SELECT} w-fit`}
            value={now.forget_after_days ?? ""}
            disabled={!now.remember}
            onChange={(e) => set({ forget_after_days: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">Never</option>
            {withSaved(DAYS, saved.forget_after_days).map((d) => (
              <option key={d} value={d}>
                {d === 1 ? "1 day" : `${d} days`}
              </option>
            ))}
          </select>
          <span className="text-xs text-pencil">
            Older lessons are hidden from the tutor, not removed. Choose Never to bring them back.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-semibold">Repeat the end of the last lesson, word for word</span>
          <select
            className={`${SELECT} w-fit`}
            value={now.recent_lines}
            disabled={!now.remember}
            onChange={(e) => set({ recent_lines: Number(e.target.value) })}
          >
            <option value={0}>Off</option>
            {withSaved(LINES, saved.recent_lines).map((n) => (
              <option key={n} value={n}>
                The last {n} things the student wrote
              </option>
            ))}
          </select>
          <span className="text-xs text-pencil">
            With the tutor&apos;s replies, from the student&apos;s last lesson in the same subject.
          </span>
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-rule pt-3 text-sm">
        <Button size="sm" disabled={busy || !changed} onClick={() => tryTo(() => researchApi.saveMemory(researchKey, now), "Saved.")}>
          Save
        </Button>
        {changed && (
          <Button size="sm" variant="plain" disabled={busy} onClick={() => setDraft(null)}>
            Put back
          </Button>
        )}
        {done && <span className="text-pencil">{done}</span>}
        <span className="ml-auto text-pencil">
          {data.students ? `Something is remembered about ${students}.` : "Nothing is remembered about your students yet."}
        </span>
        {data.students > 0 && !asking && (
          <Button size="sm" variant="red" disabled={busy} onClick={() => setAsking(true)}>
            Delete what is remembered
          </Button>
        )}
      </div>

      {asking && (
        <div className="mt-3">
          <Notice tone="amber">
            <p>
              This deletes what the tutor remembers about {students}, for every teacher&apos;s lessons,
              and it cannot be brought back. The lessons themselves stay in the record, with every
              message and mark, but the tutor will not be told about them again.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="red" disabled={busy} onClick={() => tryTo(() => researchApi.deleteMemory(researchKey), "Deleted.")}>
                Delete it
              </Button>
              <Button size="sm" variant="quiet" disabled={busy} onClick={() => setAsking(false)}>
                Keep it
              </Button>
            </div>
          </Notice>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
    </Panel>
  );
}

/** Whether the tutor may adapt how it asks each step to the student in front of it. One switch,
 * saved as it is pressed. It reads and writes the same settings as the memory panel. */
export function TutorPanel({ researchKey }: { researchKey: string }) {
  const { data, error: unread, mutate } = useSWR(["research-memory", researchKey], () =>
    researchApi.memory(researchKey),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (unread) return <ErrorNote>{(unread as ApiError).message}</ErrorNote>;
  if (!data) return null;

  async function set(on: boolean) {
    if (!data) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const saved = await researchApi.saveMemory(researchKey, { ...data.settings, adapt_to_student: on });
      await mutate(saved, { revalidate: false });
      setDone("Saved.");
    } catch (e) {
      setError((e as ApiError).message);
    }
    setBusy(false);
  }

  return (
    <Panel title="How the tutor teaches" description="For every lesson of yours, from the tutor's next reply.">
      <label className="flex items-start gap-3 text-sm text-ink">
        <input
          type="checkbox"
          className="mt-0.5 shrink-0"
          checked={data.settings.adapt_to_student}
          disabled={busy}
          onChange={(e) => set(e.target.checked)}
        />
        <span>
          <span className="font-semibold">Let the tutor adapt to each student</span>
          <span className="block text-xs text-pencil">
            The tutor decides how to ask each step for each student, from their earlier lessons and how
            today is going: a little more for a student who finds it easy, more support for one who
            does not. The objectives, the finish lines and your help rules stay as you set them. Off:
            every student is asked each step as the lesson has it.
          </span>
        </span>
      </label>
      {done && <p className="mt-2 text-sm text-pencil">{done}</p>}
      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
    </Panel>
  );
}
