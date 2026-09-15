"use client";

import { use, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { api, ApiError, type HistoryLine, type Item, type StudentSession } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import {
  Button,
  Cross,
  ErrorNote,
  Notice,
  Skeleton,
  SubjectName,
  Tick,
  TimeLeft,
} from "@/components/ui";

// Often enough that a pause, an ending or a note from the teacher shows up
// while the student is still looking at the question.
const POLL_MS = 6000;

export default function StudentWork({ params }: PageProps<"/student/[sessionId]">) {
  const { sessionId } = use(params);
  const me = useSignedIn("student");

  const { data: session, error: loadError, mutate } = useSWR<StudentSession>(
    me ? ["student-session", sessionId] : null,
    () => api.studentSession(sessionId),
    { refreshInterval: POLL_MS, keepPreviousData: true },
  );

  const [chosen, setChosen] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [justSolved, setJustSolved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // The first unsolved question, until the student picks one themselves.
  const active: Item | undefined =
    session?.items.find((i) => i.id === chosen) ??
    session?.items.find((i) => !i.solved) ??
    session?.items[0];

  const historyLength = active?.history.length ?? 0;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [historyLength, pending]);

  if (!me) return null;

  const open = session?.status === "open";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!active || !answer.trim() || pending !== null || !open) return;
    const mine = answer.trim();
    // Pin the question being answered. Without this, a right answer would
    // move "the first unsolved question" on before the student saw the tick.
    setChosen(active.id);
    setPending(mine);
    setAnswer("");
    setError(null);
    try {
      const result = await api.submitAttempt(sessionId, active.id, mine);
      if (result.correct) setJustSolved(active.id);
      await mutate();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) await mutate();
      else {
        setAnswer(mine);
        setError(`That didn't send. ${err.message}`);
      }
    } finally {
      setPending(null);
      inputRef.current?.focus();
    }
  }

  async function askForTeacher() {
    try {
      await api.requestTeacher(sessionId);
      setAsked(true);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) await mutate();
      else setError(err.message);
    }
  }

  function goTo(item: Item) {
    setChosen(item.id);
    setError(null);
    setAnswer("");
  }

  const index = session && active ? session.items.indexOf(active) : -1;
  const next = session?.items.slice(index + 1).find((i) => !i.solved) ?? session?.items.find((i) => !i.solved && i.id !== active?.id);
  const allDone = session ? session.items.length > 0 && session.items.every((i) => i.solved) : false;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6">
        {loadError && !session && <ErrorNote>{(loadError as ApiError).message}</ErrorNote>}
        {!session && !loadError && <Skeleton label="Loading your lesson" rows={4} />}

        {session && active && (
          <>
            <header className="mb-6">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <SubjectName subject={session.subject} />
                  <span className="text-sm">
                    {session.status === "paused" ? (
                      <span className="font-semibold text-amber">Paused</span>
                    ) : (
                      <TimeLeft closesAt={session.closes_at} status={session.status} />
                    )}
                  </span>
                </div>
                <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{session.title}</h1>
                {session.material_notes && (
                  <p className="mt-1.5 max-w-prose text-base text-pencil">{session.material_notes}</p>
                )}
              </div>
            </header>

            <div className="space-y-3" aria-live="polite">
              {session.teacher_messages.slice(-2).map((m) => (
                <div
                  key={m.at}
                  className="rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-4 py-3 text-base text-ink"
                >
                  <span className="block text-xs font-bold text-pencil">From your teacher</span>
                  {m.text}
                </div>
              ))}
              {session.status === "paused" && (
                <Notice tone="amber">Your teacher has paused the class. You can read your work, and carry on when they resume.</Notice>
              )}
              {session.status === "closed" && (
                <Notice>This lesson has ended. Your work has been saved.</Notice>
              )}
              {allDone && session.status !== "closed" && (
                <Notice tone="tick">You&apos;ve got every question right. Let your teacher know you&apos;ve finished.</Notice>
              )}
            </div>

            <nav aria-label="Questions" className="mt-6 mb-4 flex flex-wrap gap-2">
              {session.items.map((item) => {
                const current = item.id === active.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => goTo(item)}
                    aria-current={current ? "step" : undefined}
                    className={`figures inline-flex h-10 min-w-10 items-center justify-center gap-1 rounded-full border px-3 text-sm font-bold transition-colors ${
                      current
                        ? "border-ink bg-ink text-white"
                        : item.solved
                          ? "border-tick/40 bg-tick-wash text-tick hover:border-tick"
                          : "border-rule-strong bg-sheet text-ink hover:border-ink"
                    }`}
                  >
                    {item.ordinal}
                    {item.solved && !current && <Tick className="size-3.5" />}
                    <span className="sr-only">
                      {`Question ${item.ordinal}`}
                      {item.solved ? ", answered correctly" : ""}
                    </span>
                  </button>
                );
              })}
            </nav>

            <section
              aria-labelledby="prompt"
              className="overflow-hidden rounded-[var(--radius-sheet)] border border-rule bg-sheet shadow-[0_1px_0_var(--rule),0_20px_40px_-32px_rgba(31,42,68,0.4)]"
            >
              <div className="ruled relative min-h-72 pr-5 pb-8 pl-12 sm:pl-16">
                {/* The exercise book's margin. */}
                <span aria-hidden className="absolute inset-y-0 left-8 w-px bg-[#e7b9b9] sm:left-11" />
                <p className="text-xs leading-8 font-semibold text-pencil">
                  Question {active.ordinal} of {session.items.length}
                </p>
                <h2 id="prompt" className="font-serif text-xl leading-8 font-semibold text-ink sm:text-[1.6rem]">
                  {active.prompt}
                </h2>

                <ol role="list" className="mt-8">
                  {active.history.length === 0 && pending === null && (
                    <li className="leading-8 text-pencil">Work it out, then write your answer below.</li>
                  )}
                  {active.history.map((line, i) => (
                    <HistoryEntry
                      key={`${line.at}-${i}`}
                      line={line}
                      followedByHint={active.history[i + 1]?.kind === "hint"}
                      animate={line.kind === "attempt" && !!line.correct && justSolved === active.id}
                    />
                  ))}
                  {pending !== null && (
                    <li className="flex items-center gap-2 leading-8">
                      <span className="text-pencil">You wrote</span>
                      <span className="font-bold text-ink">{pending}</span>
                      <span className="text-sm text-faint">checking…</span>
                    </li>
                  )}
                </ol>
                <div ref={endRef} />
              </div>

              <div className="border-t border-rule bg-sheet px-5 py-4">
                {active.solved ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="flex items-center gap-2 font-semibold text-tick">
                      <Tick className="size-5" /> You got this one.
                    </p>
                    {next && (
                      <Button onClick={() => goTo(next)}>Go to question {next.ordinal}</Button>
                    )}
                  </div>
                ) : (
                  <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
                    <label htmlFor="answer" className="sr-only">
                      Your answer to question {active.ordinal}
                    </label>
                    <input
                      id="answer"
                      ref={inputRef}
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      disabled={!open}
                      autoComplete="off"
                      placeholder={open ? "Write your answer" : "Answers are closed"}
                      className="h-12 flex-1 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-4 text-lg text-ink placeholder:text-base placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none disabled:bg-sunken"
                    />
                    <Button type="submit" disabled={pending !== null || !answer.trim() || !open} className="h-12 px-6">
                      {pending !== null ? "Checking…" : "Check my answer"}
                    </Button>
                  </form>
                )}
                {error && (
                  <div className="mt-3">
                    <ErrorNote>{error}</ErrorNote>
                  </div>
                )}
              </div>
            </section>

            <footer className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-pencil">{session.disclosure}</p>
              <Button
                variant="quiet"
                onClick={askForTeacher}
                disabled={asked || session.status === "closed"}
              >
                {asked ? "Your teacher knows you need them" : "Ask my teacher for help"}
              </Button>
            </footer>
          </>
        )}
      </main>
    </>
  );
}

function HistoryEntry({
  line,
  followedByHint,
  animate,
}: {
  line: HistoryLine;
  followedByHint: boolean;
  animate: boolean;
}) {
  if (line.kind === "attempt") {
    return (
      <li className="leading-8">
        <span className="flex flex-wrap items-center gap-x-2">
          <span className="text-pencil">You wrote</span>
          <span className="font-bold text-ink">{line.text}</span>
          {line.correct ? (
            <span className="inline-flex items-center gap-1 font-semibold text-tick">
              <Tick animate={animate} className="-my-1 size-6" /> That&apos;s right
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-pencil">
              <Cross className="size-4" /> Not quite
            </span>
          )}
        </span>
        {!line.correct && !followedByHint && (
          <span className="block text-pencil">Have another go.</span>
        )}
      </li>
    );
  }
  // Notes keep the sheet's 2rem rhythm: a label row, then text rows, set in
  // from the student's own lines the way a reply is written in a margin.
  if (line.kind === "hint") {
    return (
      <li className="pl-6">
        <span className="block text-xs leading-8 font-bold text-pencil">Tutor</span>
        <span className="block text-base leading-8 text-ink">{line.text}</span>
      </li>
    );
  }
  return (
    <li className="pl-6">
      <span className="block text-xs leading-8 font-bold text-ink">From your teacher</span>
      <span className="block text-base leading-8 text-ink">{line.text}</span>
    </li>
  );
}
