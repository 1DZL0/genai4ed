"use client";

import { use, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { agentApi, ApiError, type Intent, type Learn } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat, type ChatLine } from "@/components/agent-chat";
import { COLUMN } from "@/components/chat";
import { ErrorNote, Skeleton, SubjectName, TimeLeft } from "@/components/ui";

// Often enough that a pause, an ending or a note from the teacher shows up while the student is working.
const POLL_MS = 8000;

const CHIPS: { label: string; intent: Intent }[] = [
  { label: "I don't understand", intent: "dont_understand" },
  { label: "Explain it another way", intent: "another_way" },
  { label: "Give me an example", intent: "example" },
  { label: "Why is my answer wrong?", intent: "why_wrong" },
];

const LINK =
  "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink disabled:no-underline disabled:hover:text-pencil";

/** The lesson is a conversation with the class agent, and the page is little else. */
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
  const closed = data?.status === "closed";

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader me={me} />

      {data && (
        <div className="shrink-0 border-b border-rule bg-sheet">
          <div
            className={`${COLUMN} flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-2.5`}
          >
            <h1 className="min-w-0 truncate font-serif text-lg font-semibold text-ink">
              {data.title}
            </h1>
            <p className="flex flex-wrap items-baseline gap-x-4 text-sm text-pencil">
              <SubjectName subject={data.subject} />
              {data.steps.length > 0 && (
                <span className="figures">
                  {data.completed
                    ? "Finished"
                    : `Part ${data.step_index + 1} of ${data.steps.length}`}
                </span>
              )}
              {data.status === "paused" ? (
                <span className="font-semibold text-amber">Paused</span>
              ) : (
                <TimeLeft closesAt={data.closes_at} status={data.status} />
              )}
            </p>
          </div>
        </div>
      )}

      {!data && (
        <main className={`${COLUMN} flex-1 py-8`}>
          {loadError ? (
            <ErrorNote>{(loadError as ApiError).message}</ErrorNote>
          ) : (
            <Skeleton label="Loading your lesson" rows={4} />
          )}
        </main>
      )}

      {data && (
        <main aria-label="Your lesson conversation" className="flex min-h-0 flex-1 flex-col">
          <AgentChat
            lines={lines}
            pending={pending !== null || Boolean(opening)}
            pendingText={opening ? "Getting your lesson ready" : "Reading what you wrote"}
            onSend={send}
            chips={data.can_talk ? CHIPS : []}
            placeholder={closed ? "This lesson has ended" : "Write your answer or ask a question"}
            disabled={!data.can_talk}
            task={closed ? null : data.task}
            above={
              data.result && (
                <section
                  aria-label="Your result"
                  className="mb-6 rounded-[var(--radius-sheet)] border border-tick/50 bg-sheet px-5 py-4"
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
              )
            }
            notice={
              error ? (
                <ErrorNote>{error}</ErrorNote>
              ) : data.status === "paused" ? (
                <p className="text-amber">
                  Your teacher has paused the class. You can read back, and carry on when they
                  resume.
                </p>
              ) : closed && !data.result ? (
                <p className="text-pencil">This lesson has ended. Your conversation is saved.</p>
              ) : data.completed && !closed ? (
                <p className="text-tick">
                  You&apos;ve finished the activity. You can still ask the agent questions.
                </p>
              ) : null
            }
            actions={
              !closed && (
                <button type="button" onClick={askTeacher} disabled={asked} className={LINK}>
                  {asked ? "Your teacher knows you need them" : "Ask my teacher"}
                </button>
              )
            }
            footnote={data.disclosure}
          />
        </main>
      )}
    </div>
  );
}
