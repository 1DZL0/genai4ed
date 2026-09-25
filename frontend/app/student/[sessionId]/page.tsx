"use client";

import { use, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { agentApi, ApiError, type Intent, type Learn } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat, type ChatLine } from "@/components/agent-chat";
import { Button, ErrorNote, Notice, Skeleton, SubjectName, Tick, TimeLeft } from "@/components/ui";

// Often enough that a pause, an ending or a note from the teacher shows up while the student is working.
const POLL_MS = 8000;

const CHIPS: { label: string; intent: Intent }[] = [
  { label: "I don't understand", intent: "dont_understand" },
  { label: "Explain it another way", intent: "another_way" },
  { label: "Give me an example", intent: "example" },
  { label: "Why is my answer wrong?", intent: "why_wrong" },
];

export default function StudentLesson({ params }: PageProps<"/student/[sessionId]">) {
  const { sessionId } = use(params);
  const me = useSignedIn("student");
  const { data, error: loadError, mutate } = useSWR<Learn>(
    me ? ["learn", sessionId] : null,
    () => agentApi.learn(sessionId),
    { refreshInterval: POLL_MS, keepPreviousData: true },
  );
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  const started = useRef(false);

  // The agent opens the lesson the first time it's seen.
  useEffect(() => {
    if (!data || started.current || data.lines.length > 0 || !data.can_talk) return;
    started.current = true;
    agentApi
      .learnStart(sessionId)
      .then((view) => mutate(view, { revalidate: false }))
      .catch((e: ApiError) => setError(e.message));
  }, [data, sessionId, mutate]);

  if (!me) return null;

  async function send(text: string, intent?: string) {
    setError(null);
    setPending(text || CHIPS.find((c) => c.intent === intent)?.label || "");
    try {
      const view = await agentApi.learnSay(sessionId, text, intent as Intent | undefined);
      await mutate(view, { revalidate: false });
    } catch (e) {
      setError((e as ApiError).message);
      await mutate();
    } finally {
      setPending(null);
    }
  }

  async function askTeacher() {
    try {
      await mutate(await agentApi.learnAskTeacher(sessionId), { revalidate: false });
      setAsked(true);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  const lines: ChatLine[] = (data?.lines ?? []).map((l) => ({
    id: l.id,
    who: l.who === "student" ? "me" : l.who === "agent" ? "agent" : "note",
    text: l.text,
  }));
  if (pending) lines.push({ id: "pending", who: "me", text: pending });
  const opening = data && data.lines.length === 0 && data.can_talk;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6 sm:px-6">
        {loadError && !data && <ErrorNote>{(loadError as ApiError).message}</ErrorNote>}
        {!data && !loadError && <Skeleton label="Loading your lesson" rows={4} />}

        {data && (
          <>
            <header className="mb-4">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <SubjectName subject={data.subject} />
                <span className="text-sm">
                  {data.status === "paused" ? (
                    <span className="font-semibold text-amber">Paused</span>
                  ) : (
                    <TimeLeft closesAt={data.closes_at} status={data.status} />
                  )}
                </span>
              </div>
              <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{data.title}</h1>

              <ol aria-label="Your progress" className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-2">
                {data.steps.map((step, i) => (
                  <li key={`${step.name}-${i}`} className="flex items-center gap-2 text-sm">
                    {i > 0 && <span aria-hidden className="h-px w-4 bg-rule-strong" />}
                    <span
                      aria-current={step.state === "current" ? "step" : undefined}
                      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 ${
                        step.state === "current"
                          ? "bg-ink font-semibold text-white"
                          : step.state === "done"
                            ? "bg-tick-wash text-tick"
                            : "bg-sunken text-pencil"
                      }`}
                    >
                      {step.state === "done" && <Tick className="size-3.5" />}
                      {step.name}
                      <span className="sr-only">
                        {step.state === "done" ? " (done)" : step.state === "current" ? " (now)" : ""}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </header>

            {data.status === "paused" && (
              <div className="mb-3">
                <Notice tone="amber">Your teacher has paused the class. You can read back; carry on when they resume.</Notice>
              </div>
            )}
            {data.status === "closed" && !data.result && (
              <div className="mb-3">
                <Notice>This lesson has ended. Your conversation has been saved.</Notice>
              </div>
            )}
            {data.result && (
              <section
                aria-label="Your result"
                className="mb-3 rounded-[var(--radius-sheet)] border border-tick/50 bg-sheet px-5 py-4"
              >
                <p className="text-xs font-semibold text-pencil">Your result from your teacher</p>
                <p className="figures mt-1 font-serif text-2xl font-semibold text-ink">
                  {data.result.total} / {data.result.out_of}
                </p>
                <ul className="mt-1 flex flex-wrap gap-x-4 text-sm text-pencil">
                  {data.result.criteria.map((c) => (
                    <li key={c.name} className="figures">
                      {c.name} {c.points} / {c.max}
                    </li>
                  ))}
                </ul>
                {data.result.comment && (
                  <p className="mt-2 text-base text-ink">&ldquo;{data.result.comment}&rdquo;</p>
                )}
              </section>
            )}
            {data.completed && data.status !== "closed" && (
              <div className="mb-3">
                <Notice tone="tick">You&apos;ve finished the activity. You can still ask the agent questions.</Notice>
              </div>
            )}

            {data.task && data.status !== "closed" && (
              <section
                aria-label="What you're working on"
                className="mb-3 rounded-[var(--radius-sheet)] border border-rule-strong bg-sheet px-5 py-4"
              >
                <p className="text-xs font-semibold text-pencil">Working on</p>
                <p className="mt-1 font-serif text-lg leading-snug font-semibold text-ink">{data.task}</p>
              </section>
            )}

            <section
              aria-label="Your lesson conversation"
              className="flex min-h-[26rem] flex-1 flex-col rounded-[var(--radius-sheet)] border border-rule bg-paper p-4"
            >
              {error && (
                <div className="mb-2">
                  <ErrorNote>{error}</ErrorNote>
                </div>
              )}
              <AgentChat
                lines={lines}
                pending={pending !== null || Boolean(opening)}
                pendingText={opening ? "Getting your lesson ready…" : "The agent is reading your answer…"}
                onSend={send}
                chips={data.can_talk ? CHIPS : []}
                placeholder="Write your answer or ask a question"
                disabled={!data.can_talk}
                disabledReason={data.status === "paused" ? "Paused by your teacher." : undefined}
              />
            </section>

            <footer className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-pencil">{data.disclosure}</p>
              {data.status !== "closed" && (
                <Button variant="quiet" onClick={askTeacher} disabled={asked}>
                  {asked ? "Your teacher knows you need them" : "Ask my teacher"}
                </Button>
              )}
            </footer>
          </>
        )}
      </main>
    </>
  );
}
