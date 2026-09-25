"use client";

import { useState } from "react";
import {
  ApiError,
  researchApi,
  type Instructions,
  type ResearchSummary,
} from "@/lib/api";
import { inputClass } from "@/components/auth-layout";
import { Button, Empty, ErrorNote, Panel, QUEUE_WORDS } from "@/components/ui";

const CONFLICT_WORDS: Record<string, string> = {
  over_disclosure: "Gave more than the rules allow",
  answer_leakage: "Stated the answer",
  wrote_the_work: "Wrote the work",
  skipped_assessment: "Moved on without judging",
  off_ladder: "Help out of ladder order",
  malformed_output: "Unreadable reply",
};

function counts(found: Record<string, number>, words: Record<string, string>) {
  const entries = Object.entries(found);
  if (entries.length === 0) return "None";
  return entries.map(([kind, n]) => `${words[kind] ?? kind}: ${n}`).join(", ");
}

export default function ResearchPage() {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<ResearchSummary | null>(null);
  const [told, setTold] = useState<Instructions | null>(null);

  async function tryTo(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError((e as ApiError).message);
    }
    setBusy(false);
  }

  async function open(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setFound(await researchApi.summary(key));
    } catch (e) {
      setError(
        (e as ApiError).status === 404
          ? "That key was not accepted, or no research key is set on the server."
          : (e as ApiError).message,
      );
    }
    setBusy(false);
  }

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-8">
      <header>
        <h1 className="text-xl font-bold text-ink">Research view</h1>
        <p className="mt-1 text-sm text-pencil">
          Counts per lesson and condition, read from the platform&apos;s
          records. No names and nothing a student wrote appears here.
        </p>
      </header>

      <form onSubmit={open} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-ink">
          Research key
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className={inputClass}
          />
        </label>
        <Button type="submit" disabled={busy || !key}>
          {found ? "Refresh" : "Open"}
        </Button>
      </form>
      {error && <ErrorNote>{error}</ErrorNote>}

      {found && (
        <>
          <Panel
            title="Study settings"
            description="Set in the server's environment, not here."
          >
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              <Setting
                name="Study"
                value={found.study.active ? "Running" : "Not running"}
              />
              <Setting name="Help policy" value={found.study.policy} />
              <Setting
                name="Rule checks"
                value={found.study.supervisor ? "Enforced" : "Recorded only"}
              />
              <Setting name="Model" value={found.study.model} />
            </dl>
          </Panel>

          <Panel
            title="The records"
            description="Every turn, evidence record and alert as CSV files, students by pseudonym."
          >
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={busy}
                onClick={() => tryTo(() => researchApi.download(key, false))}
              >
                Download the records
              </Button>
              <Button
                size="sm"
                variant="quiet"
                disabled={busy}
                onClick={() => tryTo(() => researchApi.download(key, true))}
              >
                Download with what was written
              </Button>
            </div>
          </Panel>

          <Panel
            title="What the agent is told"
            description="The fixed instructions it works under, as they are in the code. The teacher's rules are added to these per lesson."
          >
            {told ? (
              <div className="space-y-4 text-sm">
                {(["teacher", "student", "review"] as const).map((part) => (
                  <details key={part}>
                    <summary className="cursor-pointer font-semibold text-ink">
                      {part === "teacher"
                        ? "Talking to the teacher"
                        : part === "student"
                          ? "Teaching a student"
                          : "Suggesting outcomes"}
                    </summary>
                    <pre className="mt-2 max-h-96 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink">
                      {told[part]}
                    </pre>
                  </details>
                ))}
              </div>
            ) : (
              <Button
                size="sm"
                variant="quiet"
                disabled={busy}
                onClick={() =>
                  tryTo(async () =>
                    setTold(await researchApi.instructions(key)),
                  )
                }
              >
                Show the instructions
              </Button>
            )}
          </Panel>

          {found.lessons.length === 0 && (
            <Empty>No lesson has had a student turn yet.</Empty>
          )}
          {found.lessons.map((lesson) => (
            <Panel
              key={lesson.session_id}
              title={lesson.lesson || "Untitled lesson"}
              description={`${lesson.status} · ${lesson.models.join(", ")} · ${lesson.prompt_versions.join(", ")}`}
            >
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-pencil">
                    <tr>
                      <th className="py-1 pr-4 font-normal">Condition</th>
                      <th className="py-1 pr-4 font-normal">Students</th>
                      <th className="py-1 pr-4 font-normal">Turns</th>
                      <th className="py-1 pr-4 font-normal">Held back</th>
                      <th className="py-1 pr-4 font-normal">Mean reply</th>
                      <th className="py-1 pr-4 font-normal">Mean outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lesson.arms.map((arm) => (
                      <tr
                        key={arm.arm}
                        className="border-t border-rule align-top text-ink"
                      >
                        <td className="py-2 pr-4">
                          {arm.arm}
                          <p className="text-xs text-pencil">
                            First drafts:{" "}
                            {counts(arm.conflicts, CONFLICT_WORDS)}
                          </p>
                        </td>
                        <td className="py-2 pr-4">{arm.students}</td>
                        <td className="py-2 pr-4">{arm.turns}</td>
                        <td className="py-2 pr-4">{arm.held_back}</td>
                        <td className="py-2 pr-4">
                          {(arm.mean_latency_ms / 1000).toFixed(1)}s
                        </td>
                        <td className="py-2 pr-4">
                          {arm.mean_confirmed ??
                            arm.mean_suggested ??
                            "None yet"}
                          {arm.mean_confirmed === null &&
                            arm.mean_suggested !== null && (
                              <span className="text-xs text-pencil">
                                {" "}
                                suggested
                              </span>
                            )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-pencil">
                Alerts to the teacher: {counts(lesson.alerts, QUEUE_WORDS)}
              </p>
            </Panel>
          ))}
        </>
      )}
    </main>
  );
}

function Setting({ name, value }: { name: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-pencil">{name}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
