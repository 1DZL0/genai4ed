"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  api,
  ApiError,
  type HistoryLine,
  type Item,
  type StudentSession,
  type TutorAsk,
} from "@/lib/api";
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

/**
 * A student's lesson: questions to answer, or writing tasks with their tutor.
 *
 * With `preview` (a pseudonym), it is the teacher's read-only look at that
 * student's screen, loaded by `load`; nothing can be typed or sent.
 */
export function StudentLesson({
  sessionId,
  load,
  preview,
}: {
  sessionId: string;
  load: () => Promise<StudentSession>;
  preview?: string;
}) {
  const { data: session, error: loadError, mutate } = useSWR<StudentSession>(
    ["student-session", sessionId, preview ?? "me"],
    load,
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

  const live = session?.status === "open";
  const open = live && !preview;

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
  const next = session?.items.slice(index + 1).find((i) => !done(i)) ?? session?.items.find((i) => !done(i) && i.id !== active?.id);
  const allDone = session ? session.items.length > 0 && session.items.every(done) : false;
  const writing = active?.kind === "written_response";

  return (
    <>
      <main className={`mx-auto w-full flex-1 px-4 py-8 sm:px-6 ${writing ? "max-w-5xl" : "max-w-3xl"}`}>
        {preview && (
          <div className="mb-6 rounded-[var(--radius-control)] border border-rule-strong bg-sunken px-4 py-3 text-sm text-ink">
            <span className="font-semibold">What {preview} sees right now.</span> A read-only
            preview: it updates as they work, and nothing here can be changed.
          </div>
        )}
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
                {session.material_notes && !writing && (
                  <p className="mt-1.5 max-w-prose text-base text-pencil">{session.material_notes}</p>
                )}
                {session.phase_name && session.status === "open" && (
                  <p className="mt-1.5 text-sm text-pencil">
                    Now: <span className="font-semibold text-ink">{session.phase_name}</span>
                  </p>
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
              {live && !session.tutors_on && (
                <Notice>
                  Tutors are off right now. Listen to your teacher. You can still read and write
                  your work.
                </Notice>
              )}
              {allDone && session.status !== "closed" && (
                <Notice tone="tick">
                  {session.items.some((i) => i.kind === "written_response")
                    ? "You've handed in every task. Let your teacher know you've finished."
                    : "You've got every question right. Let your teacher know you've finished."}
                </Notice>
              )}
            </div>

            <nav aria-label={writing ? "Tasks" : "Questions"} className="mt-6 mb-4 flex flex-wrap gap-2">
              {session.items.map((item) => {
                const current = item.id === active.id;
                const finished = done(item);
                const noun = item.kind === "written_response" ? "Task" : "Question";
                return (
                  <button
                    key={item.id}
                    onClick={() => goTo(item)}
                    aria-current={current ? "step" : undefined}
                    className={`figures inline-flex h-10 min-w-10 items-center justify-center gap-1 rounded-full border px-3 text-sm font-bold transition-colors ${
                      current
                        ? "border-ink bg-ink text-white"
                        : finished
                          ? "border-tick/40 bg-tick-wash text-tick hover:border-tick"
                          : "border-rule-strong bg-sheet text-ink hover:border-ink"
                    }`}
                  >
                    {item.ordinal}
                    {finished && !current && <Tick className="size-3.5" />}
                    <span className="sr-only">
                      {`${noun} ${item.ordinal}`}
                      {finished ? (item.kind === "written_response" ? ", handed in" : ", answered correctly") : ""}
                    </span>
                  </button>
                );
              })}
            </nav>

            {writing ? (
              <WritingTask
                key={active.id}
                sessionId={sessionId}
                item={active}
                total={session.items.length}
                open={open}
                tutorsOn={session.tutors_on}
                canSave={session.status !== "closed" && !preview}
                preview={Boolean(preview)}
                notes={session.material_notes}
                next={next}
                onChanged={() => mutate()}
                onNext={goTo}
              />
            ) : (
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
            )}

            <footer className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-pencil">{session.disclosure}</p>
              <Button
                variant="quiet"
                onClick={askForTeacher}
                disabled={asked || session.status === "closed" || Boolean(preview)}
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

function done(item: Item) {
  return item.kind === "written_response" ? item.submitted : item.solved;
}

function wordCount(text: string) {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

// Long enough that typing isn't interrupted, short enough that little is lost.
const AUTOSAVE_MS = 1500;

const ASKS: { ask: TutorAsk; label: string }[] = [
  { ask: "stuck", label: "I'm stuck" },
  { ask: "language", label: "Check my language" },
  { ask: "feedback", label: "What do you think?" },
];

function WritingTask({
  sessionId,
  item,
  total,
  open,
  tutorsOn,
  canSave,
  preview,
  notes,
  next,
  onChanged,
  onNext,
}: {
  sessionId: string;
  item: Item;
  total: number;
  open: boolean;
  tutorsOn: boolean;
  canSave: boolean;
  preview: boolean;
  notes: string | null;
  next: Item | undefined;
  onChanged: () => void;
  onNext: (item: Item) => void;
}) {
  // Taken from the server once, when the task opens. Polls must never
  // overwrite what the student is typing.
  const [text, setText] = useState(item.text);
  const [saved, setSaved] = useState<"saved" | "saving" | "unsaved" | "failed">("saved");
  const [asking, setAsking] = useState<TutorAsk | null>(null);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSaved = useRef(item.text);
  const endRef = useRef<HTMLDivElement>(null);

  const locked = item.submitted || !canSave;
  const canAsk = open && tutorsOn && !item.submitted;

  useEffect(() => {
    if (locked || text === lastSaved.current) return;
    setSaved("unsaved");
    const timer = window.setTimeout(async () => {
      setSaved("saving");
      try {
        await api.saveDraft(sessionId, item.id, text);
        lastSaved.current = text;
        setSaved("saved");
      } catch {
        setSaved("failed");
      }
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [text, locked, sessionId, item.id]);

  const historyLength = item.history.length;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [historyLength, asking]);

  async function ask(how: TutorAsk) {
    if (!canAsk || asking) return;
    if (how === "question" && !question.trim()) return;
    setAsking(how);
    setError(null);
    try {
      await api.askTutor(sessionId, item.id, how, text, how === "question" ? question.trim() : "");
      lastSaved.current = text;
      setSaved("saved");
      if (how === "question") setQuestion("");
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.message);
      if (err.status === 409) onChanged();
    } finally {
      setAsking(null);
    }
  }

  async function submit() {
    if (!text.trim() || submitting) return;
    if (!window.confirm("Hand this in? You won't be able to change it after.")) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.submitWritten(sessionId, item.id, text);
      lastSaved.current = text;
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.message);
      if (err.status === 409) onChanged();
    } finally {
      setSubmitting(false);
    }
  }

  // A preview follows the student's saved work as it changes.
  const shown = preview ? item.text : text;
  const words = wordCount(shown);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <section
        aria-labelledby="task"
        className="overflow-hidden rounded-[var(--radius-sheet)] border border-rule bg-sheet shadow-[0_1px_0_var(--rule),0_20px_40px_-32px_rgba(31,42,68,0.4)]"
      >
        <div className="relative pr-5 pb-4 pl-12 sm:pl-16">
          <span aria-hidden className="absolute inset-y-0 left-8 w-px bg-[#e7b9b9] sm:left-11" />
          <p className="text-xs leading-8 font-semibold text-pencil">
            Task {item.ordinal} of {total}
          </p>
          <h2 id="task" className="font-serif text-xl leading-8 font-semibold text-ink sm:text-[1.4rem]">
            {item.prompt}
          </h2>

          <label htmlFor="paragraph" className="sr-only">
            Your paragraph for task {item.ordinal}
          </label>
          <textarea
            id="paragraph"
            value={shown}
            onChange={(e) => setText(e.target.value)}
            readOnly={locked}
            rows={12}
            placeholder={preview ? "Nothing written yet." : locked ? "" : "Start with your argument in one sentence."}
            className="ruled mt-4 block min-h-80 w-full resize-y border-0 bg-transparent font-serif text-lg leading-8 text-ink placeholder:text-faint focus:outline-none read-only:cursor-default"
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule px-5 py-3">
          <p className="figures text-sm text-pencil" aria-live="polite">
            {words} word{words === 1 ? "" : "s"}
            {!locked && (
              <span className="ml-3 text-faint">
                {saved === "saving"
                  ? "Saving…"
                  : saved === "unsaved"
                    ? ""
                    : saved === "failed"
                      ? "Not saved. Check your connection."
                      : text
                        ? "Saved"
                        : ""}
              </span>
            )}
          </p>
          {item.submitted ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="flex items-center gap-2 font-semibold text-tick">
                <Tick className="size-5" /> Handed in
              </p>
              {next && <Button onClick={() => onNext(next)}>Go to task {next.ordinal}</Button>}
            </div>
          ) : (
            <Button onClick={submit} disabled={!text.trim() || submitting || !canSave}>
              {submitting ? "Handing in…" : "Hand it in"}
            </Button>
          )}
        </div>

        {item.submitted && <ScoreCard item={item} />}

        {item.rubric.length > 0 && (
          <details className="border-t border-rule px-5 py-3 text-sm">
            <summary className="cursor-pointer font-semibold text-ink">How this is marked</summary>
            <ul role="list" className="mt-2 space-y-1.5">
              {item.rubric.map((c) => (
                <li key={c.name}>
                  <span className="font-semibold text-ink">
                    {c.name} <span className="figures font-normal text-pencil">({c.max} points)</span>
                  </span>
                  {c.description && <span className="block text-pencil">{c.description}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
        {notes && (
          <details className="border-t border-rule px-5 py-3 text-sm">
            <summary className="cursor-pointer font-semibold text-ink">From the board</summary>
            <p className="mt-2 whitespace-pre-line text-pencil">{notes}</p>
          </details>
        )}
      </section>

      <aside aria-labelledby="tutor" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet lg:sticky lg:top-4">
        <header className="px-5 pt-4 pb-2">
          <h2 id="tutor" className="text-base font-bold text-ink">
            Your tutor
          </h2>
          <p className="text-xs text-pencil">
            It helps you write. It won&apos;t write your paragraph for you.
          </p>
        </header>

        <ol role="list" className="max-h-96 space-y-3 overflow-y-auto px-5 py-2" aria-live="polite">
          {item.history.length === 0 && (
            <li className="text-sm text-pencil">Have a go first. Ask when you need a hand.</li>
          )}
          {item.history.map((line, i) => (
            <li
              key={`${line.at}-${i}`}
              className={
                line.kind === "ask"
                  ? "ml-8 rounded-[var(--radius-control)] bg-sunken px-3 py-2 text-sm text-ink"
                  : "mr-4 rounded-[var(--radius-control)] border border-rule px-3 py-2 text-sm text-ink"
              }
            >
              <span className="block text-xs font-bold text-pencil">
                {line.kind === "ask" ? "You" : line.kind === "hint" ? "Tutor" : "From your teacher"}
              </span>
              {line.text}
            </li>
          ))}
          {asking && (
            <li className="mr-4 px-3 py-2 text-sm text-faint">The tutor is reading your work…</li>
          )}
          <div ref={endRef} />
        </ol>

        {item.submitted ? (
          <p className="border-t border-rule px-5 py-4 text-sm text-pencil">
            This task is handed in, so the tutor has finished with it.
          </p>
        ) : (
        <div className="border-t border-rule px-5 py-4">
          {!canAsk && (
            <p className="mb-3 text-sm text-pencil">
              {preview
                ? tutorsOn
                  ? "The student asks their tutor with these buttons."
                  : "Tutors are off right now."
                : open
                  ? "Tutors are off right now."
                  : "The tutor isn't available now."}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {ASKS.map(({ ask: how, label }) => (
              <Button
                key={how}
                size="sm"
                variant="quiet"
                disabled={!canAsk || asking !== null}
                onClick={() => ask(how)}
              >
                {label}
              </Button>
            ))}
          </div>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              ask("question");
            }}
          >
            <label htmlFor="question" className="sr-only">
              Ask the tutor a question
            </label>
            <input
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={!canAsk}
              maxLength={500}
              placeholder="Or type a question"
              className="h-9 min-w-0 flex-1 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink placeholder:text-faint focus:border-ink focus:outline-none disabled:bg-sunken"
            />
            <Button type="submit" size="sm" disabled={!canAsk || !question.trim() || asking !== null}>
              Ask
            </Button>
          </form>
          {error && (
            <div className="mt-3">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}
        </div>
        )}
      </aside>
    </div>
  );
}

function ScoreCard({ item }: { item: Item }) {
  const score = item.score;
  if (!score) {
    return (
      <p className="border-t border-rule px-5 py-3 text-sm text-pencil">
        Your teacher will mark this. Your score shows here once they have.
      </p>
    );
  }
  return (
    <div className="border-t border-rule px-5 py-4 text-sm">
      <p className="flex items-baseline gap-2">
        <span className="font-bold text-ink">Your score</span>
        <span className="figures font-serif text-2xl font-semibold text-ink">
          {score.total}
          <span className="text-base text-pencil">/{score.out_of}</span>
        </span>
      </p>
      <ul role="list" className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        {score.criteria.map((c) => (
          <li key={c.name} className="figures text-pencil">
            {c.name} <span className="font-semibold text-ink">{c.points}</span>/{c.max}
          </li>
        ))}
      </ul>
      {score.keep && (
        <p className="mt-3 text-ink">
          <span className="font-semibold">What went well: </span>
          {score.keep}
        </p>
      )}
      {score.develop.length > 0 && (
        <div className="mt-2 text-ink">
          <span className="font-semibold">To work on next:</span>
          <ul className="mt-1 list-disc pl-5">
            {score.develop.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {score.comment && (
        <p className="mt-3 text-ink">
          <span className="font-semibold">From your teacher: </span>
          {score.comment}
        </p>
      )}
    </div>
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
