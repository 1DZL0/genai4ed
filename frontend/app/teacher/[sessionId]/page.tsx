"use client";

import { use, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import { api, ApiError, type Console, type QueueItem, type TranscriptLine } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import {
  Button,
  DevBanner,
  Empty,
  ErrorNote,
  Panel,
  SeverityTag,
  Skeleton,
} from "@/components/ui";

const POLL_MS = 4000;

function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function TeacherConsole({ params }: PageProps<"/teacher/[sessionId]">) {
  const { sessionId } = use(params);
  const router = useRouter();

  const who = useIdentity();
  const [actionError, setActionError] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<{
    pseudonym: string;
    lines: TranscriptLine[];
  } | null>(null);

  // Polling rather than SSE: EventSource cannot carry the identity header, and
  // concept note S3 offers polling as equally sufficient for a class of 25-30.
  // SWR also revalidates when the teacher returns to the tab, which matters
  // when she has been away from the laptop helping someone.
  const {
    data,
    error: loadError,
    mutate,
  } = useSWR<Console>(
    who ? ["console", who, sessionId] : null,
    () => api.console(who as string, sessionId),
    { refreshInterval: POLL_MS, keepPreviousData: true },
  );

  const error = actionError ?? (loadError ? (loadError as ApiError).message : null);

  async function acknowledge(item: QueueItem) {
    if (!who || !data) return;
    // Optimistic: clearing an item should feel immediate in a classroom.
    await mutate(
      async () => {
        await api.acknowledge(who, item.id);
        return api.console(who, sessionId);
      },
      {
        optimisticData: { ...data, queue: data.queue.filter((q) => q.id !== item.id) },
        rollbackOnError: true,
      },
    ).catch((e) => setActionError((e as ApiError).message));
  }

  async function openTranscript(studentId: string, pseudonym: string) {
    if (!who) return;
    try {
      setDrilldown({ pseudonym, lines: await api.transcript(who, sessionId, studentId) });
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  async function setState(to: "open" | "paused") {
    if (!who) return;
    try {
      await mutate(api.setSessionState(who, sessionId, to), { revalidate: false });
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  if (who === undefined) return null; // still hydrating
  if (who === null) return <NotIdentified />;

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        {!data && !error && <Skeleton label="Loading the console" rows={5} />}

        {data && (
          <>
            <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold text-ink">{data.title}</h1>
                <p className="mt-0.5 text-sm text-muted">
                  {data.items} questions · session {data.status} · {data.progress.length} students
                </p>
              </div>
              {data.status === "open" ? (
                <Button variant="quiet" onClick={() => setState("paused")}>
                  Pause activity
                </Button>
              ) : (
                <Button onClick={() => setState("open")}>Resume activity</Button>
              )}
            </header>

            <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
              <Panel
                title="Needs you"
                aside={
                  <span className="text-xs text-muted">
                    {data.queue.length === 0 ? "clear" : `${data.queue.length} open`}
                  </span>
                }
              >
                {data.queue.length === 0 ? (
                  <Empty>Nothing needs you. The class is working.</Empty>
                ) : (
                  <ul role="list" className="divide-y divide-border-subtle">
                    {data.queue.map((item) => (
                      <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-sm font-medium text-ink">
                                {item.pseudonym}
                              </span>
                              <SeverityTag kind={item.kind} priority={item.priority} />
                            </div>
                            <p className="mt-1 text-sm text-ink">{item.summary}</p>
                            <p className="mt-1 text-xs text-faint">
                              {item.supporting_record_ids.length} piece
                              {item.supporting_record_ids.length === 1 ? "" : "s"} of evidence ·{" "}
                              {clockTime(item.created_at)}
                            </p>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <Button
                              variant="quiet"
                              onClick={() => openTranscript(item.student_id, item.pseudonym)}
                            >
                              Look
                            </Button>
                            <Button variant="quiet" onClick={() => acknowledge(item)}>
                              Done
                            </Button>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel title="Progress">
                <ul role="list" className="divide-y divide-border-subtle">
                  {data.progress.map((student) => (
                    <li
                      key={student.student_id}
                      className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
                    >
                      <span className="font-mono text-sm text-ink">{student.pseudonym}</span>
                      <span className="flex items-center gap-3">
                        <span className="text-xs text-muted">
                          {student.correct}/{data.items} correct
                          {student.attempts > 0 ? ` · ${student.attempts} attempts` : ""}
                        </span>
                        <Button
                          variant="quiet"
                          onClick={() => openTranscript(student.student_id, student.pseudonym)}
                        >
                          Look
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>

            {drilldown && (
              <div className="mt-5">
                <Panel
                  title={`${drilldown.pseudonym} — transcript`}
                  aside={
                    <button
                      onClick={() => setDrilldown(null)}
                      className="text-xs text-muted underline underline-offset-2 hover:text-ink"
                    >
                      close
                    </button>
                  }
                >
                  <p className="mb-3 text-xs text-faint">
                    This drill-down has been recorded in the access log, and students are told
                    their teacher can read their work.
                  </p>
                  {drilldown.lines.length === 0 ? (
                    <Empty>Nothing recorded for this student yet.</Empty>
                  ) : (
                    <ol role="list" className="space-y-2">
                      {drilldown.lines.map((line) => (
                        <li key={line.record_id} className="flex gap-3 text-sm">
                          <span className="w-14 shrink-0 font-mono text-xs text-faint">
                            {clockTime(line.created_at)}
                          </span>
                          <span className="w-20 shrink-0 text-xs text-muted">{line.kind}</span>
                          <span className="min-w-0 flex-1 text-ink">
                            {line.kind === "attempt" ? (
                              <>
                                answered{" "}
                                <span className="font-mono">{String(line.detail.answer ?? "")}</span>{" "}
                                <span className={line.correct ? "text-correct" : "text-incorrect"}>
                                  {line.correct ? "✓ correct" : "✗ not right"}
                                </span>
                              </>
                            ) : (
                              String(
                                line.detail.message ??
                                  line.detail.text ??
                                  JSON.stringify(line.detail),
                              )
                            )}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </Panel>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
