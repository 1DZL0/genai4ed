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

/** "now", "after one more try", "after 3 more tries". */
function inTries(n: number) {
  return n === 0 ? "now" : n === 1 ? "after one more try" : `after ${n} more tries`;
}

/** What help the lesson's rules allow right now, in the student's terms. */
function helpWords(h: Learn["help"]): string {
  const answer =
    h.answer_in === null ? "The final answer is never given." : `The full answer ${inTries(h.answer_in)}.`;
  if (h.ladder) return `Help comes one kind at a time, each after another try. ${answer}`;
  if (!h.hint) return `No hints or worked steps in this lesson: write your own working. ${answer}`;
  const worked =
    h.worked_step_in === null ? "" : ` A worked step on your question ${inTries(h.worked_step_in)}.`;
  return `Hints, and an example of a similar problem, any time.${worked} ${answer}`;
}

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
  // The opening failed (the model was busy, or the class was paused a moment): the box opens
  // so the student is not locked out, and the opening is tried again on a later refresh.
  const [openFailed, setOpenFailed] = useState(false);
  const started = useRef(false);

  // The agent opens the lesson the first time it's seen. Until the agent has said something:
  // an "Ask my teacher" note left while the class was paused does not count as opened.
  useEffect(() => {
    if (!data || started.current || data.lines.some((l) => l.who === "agent") || !data.can_talk)
      return;
    started.current = true;
    agentApi
      .learnStart(sessionId)
      .then((view) => {
        setOpenFailed(false);
        return mutate(view, { revalidate: false });
      })
      .catch((e: ApiError) => {
        setError(e.message);
        setOpenFailed(true);
        window.setTimeout(() => {
          started.current = false;
        }, 10_000);
      });
  }, [data, sessionId, mutate]);

  if (!me) return null;

  /** False when it did not go through, so the box gives the words back. */
  async function send(text: string, intent?: string): Promise<boolean> {
    setError(null);
    setPending(text || CHIPS.find((c) => c.intent === intent)?.label || "");
    try {
      const view = await agentApi.learnSay(sessionId, text, intent as Intent | undefined);
      await mutate(view, { revalidate: false });
      return true;
    } catch (e) {
      setError((e as ApiError).message);
      await mutate();
      return false;
    } finally {
      setPending(null);
    }
  }

  async function rate(lineId: string, helped: boolean) {
    try {
      await mutate(await agentApi.learnHelped(sessionId, lineId, helped), { revalidate: false });
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function askTeacher() {
    // Off at once, so a double tap is one call for the teacher. After that the server says
    // whether the request is still open, so a reload keeps it off and Dealt with turns it on.
    setAsked(true);
    try {
      await mutate(await agentApi.learnAskTeacher(sessionId), { revalidate: false });
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setAsked(false);
    }
  }

  const lines: ChatLine[] = (data?.lines ?? []).map((l) => ({
    id: l.id,
    who: l.who === "student" ? "me" : l.who === "agent" ? "agent" : "note",
    text: l.text,
    helped: l.helped,
  }));
  if (pending) lines.push({ id: "pending", who: "me", text: pending });
  const opening = data && !data.lines.some((l) => l.who === "agent") && data.can_talk;
  const waiting = asked || Boolean(data?.asked_teacher);
  const closed = data?.status === "closed";
  const done = data?.steps.filter((s) => s.state === "done").length ?? 0;
  const total = data?.steps.length ?? 0;
  // From the server, which reads it from the records that outlive the chat: after the chat
  // is purged a student who took part still did.
  const tookPart = Boolean(data?.took_part) || (data?.lines ?? []).some((l) => l.who === "student");
  const help = data?.help;
  // The example button gives an example of a similar problem, whenever hints are allowed.
  const chips = data?.can_talk
    ? CHIPS.map((c) =>
        c.intent === "example" && help && !help.hint
          ? { ...c, label: "No examples in this lesson", disabled: true }
          : c,
      )
    : [];

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
          {data.steps.length > 1 && (
            <ol aria-label="The steps of this lesson" className={`${COLUMN} flex flex-wrap gap-x-4 gap-y-1 pb-2.5 text-sm`}>
              {data.steps.map((s, i) => (
                <li
                  key={i}
                  className={`relative flex items-center gap-1.5 ${
                    s.state === "current" ? "font-semibold text-ink" : s.state === "done" ? "text-ink" : "text-pencil"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`figures flex size-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                      s.state === "done"
                        ? "bg-tick-wash text-tick"
                        : s.state === "current"
                          ? "bg-ink text-white"
                          : "border border-rule-strong text-pencil"
                    }`}
                  >
                    {s.state === "done" ? "\u2713" : i + 1}
                  </span>
                  {s.name}
                  <span className="sr-only">
                    {s.state === "done" ? ", done" : s.state === "current" ? ", now" : ", to come"}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {!data && (
        <main className={`${COLUMN} flex-1 py-8`}>
          {loadError ? (
            <ErrorNote>
              {[404, 422].includes((loadError as ApiError).status)
                ? "This lesson could not be found. Go back to your lessons and open it from there."
                : (loadError as ApiError).message}
            </ErrorNote>
          ) : (
            <Skeleton label="Loading your lesson" rows={4} />
          )}
        </main>
      )}

      {data && (
        <main aria-label="Your lesson conversation" className="flex min-h-0 flex-1 flex-col">
          <AgentChat
            lines={lines}
            pending={pending !== null || (Boolean(opening) && !openFailed)}
            pendingText={opening && !openFailed ? "Getting your lesson ready" : "Reading what you wrote"}
            onSend={send}
            chips={chips}
            placeholder={closed ? "This lesson has ended" : "Write your answer or ask a question"}
            disabled={!data.can_talk}
            task={closed ? null : data.task}
            above={
              closed && (
                <section
                  aria-label="How it went"
                  className="mb-6 rounded-[var(--radius-sheet)] border border-tick/50 bg-sheet px-5 py-4"
                >
                  <p className="text-xs font-semibold text-pencil">Your lesson is over</p>
                  <p className="mt-1 text-base text-ink">
                    {!tookPart && !data.result
                      ? "You did not take part in this lesson."
                      : total === 0
                        ? "Your conversation is saved."
                        : done === total
                          ? `You finished all ${total} steps.`
                          : `You got through ${done} of ${total} steps.`}
                  </p>
                  {/* A result the teacher confirmed is always shown, even one from before the
                      took-part rule, when an opening alone could be given an outcome. */}
                  {data.result ? (
                    <>
                      {data.result.out_of > 0 && (
                        <p className="figures mt-2 font-serif text-2xl font-semibold text-ink">
                          {data.result.total} / {data.result.out_of}
                        </p>
                      )}
                      {data.result.out_of > 0 && (
                        <ul className="mt-1 flex flex-wrap gap-x-4 text-sm text-pencil">
                          {data.result.criteria.map((c) => (
                            <li key={c.name} className="figures">
                              {c.name} {c.points} / {c.max}
                            </li>
                          ))}
                        </ul>
                      )}
                      {data.result.keep && (
                        <p className="mt-2 text-base text-ink">
                          <span className="font-semibold">What went well: </span>
                          {data.result.keep}
                        </p>
                      )}
                      {data.result.develop.length > 0 && (
                        <div className="mt-2 text-base text-ink">
                          <p className="font-semibold">To look at again:</p>
                          <ul className="list-disc pl-5">
                            {data.result.develop.map((d) => (
                              <li key={d}>{d}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {data.result.comment && (
                        <p className="mt-2 text-base text-ink">
                          Your teacher says: &ldquo;{data.result.comment}&rdquo;
                        </p>
                      )}
                    </>
                  ) : !tookPart ? null : (
                    <p className="mt-2 text-sm text-pencil">
                      Your teacher will add a note here once they have looked at your work.
                    </p>
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
              ) : data.completed && !closed ? (
                <p className="text-tick">
                  You&apos;ve finished the activity. You can still ask the agent questions.
                </p>
              ) : !closed && help ? (
                <p className="text-pencil">{helpWords(help)}</p>
              ) : null
            }
            actions={
              !closed && (
                <button type="button" onClick={askTeacher} disabled={waiting} className={LINK}>
                  {waiting ? "Your teacher knows you need them" : "Ask my teacher"}
                </button>
              )
            }
            footnote={data.disclosure}
            onRate={rate}
            symbols={data.can_talk}
            // The ending box, then the mark, appear above the conversation: bring them into view.
            topKey={
              closed
                ? `closed:${data.result ? `${data.result.total}:${data.result.comment ?? ""}` : ""}`
                : undefined
            }
          />
        </main>
      )}
    </div>
  );
}
