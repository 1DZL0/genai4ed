"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  api,
  ApiError,
  type Console,
  type Phase,
  type QueueItem,
  type Score,
  type StudentProgress,
  type TranscriptLine,
} from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import {
  Button,
  clockTime,
  Cross,
  ErrorNote,
  LadderGauge,
  Notice,
  QueueKind,
  RUNG_WORDS,
  Skeleton,
  SubjectName,
  Tick,
  TimeLeft,
} from "@/components/ui";

const POLL_MS = 4000;

const ASK_WORDS: Record<string, string> = {
  stuck: "I'm stuck",
  language: "Check my language",
  feedback: "What do you think?",
};

type Drilldown = { student: StudentProgress; lines: TranscriptLine[] | null };

export default function TeacherConsole({ params }: PageProps<"/teacher/[sessionId]">) {
  const { sessionId } = use(params);
  const me = useSignedIn("teacher");
  const [actionError, setActionError] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<Drilldown | null>(null);

  // Polling: concept note S3 offers it as equally sufficient for a class of
  // 25-30. SWR also revalidates when the teacher returns to the tab, which
  // matters when they have been away from the laptop helping someone.
  const {
    data,
    error: loadError,
    mutate,
  } = useSWR<Console>(me ? ["console", sessionId] : null, () => api.console(sessionId), {
    refreshInterval: POLL_MS,
    keepPreviousData: true,
  });

  const error = actionError ?? (loadError ? (loadError as ApiError).message : null);

  async function acknowledge(item: QueueItem) {
    if (!data) return;
    // Optimistic: clearing an item should feel immediate in a classroom.
    await mutate(
      async () => {
        await api.acknowledge(item.id);
        return api.console(sessionId);
      },
      {
        optimisticData: { ...data, queue: data.queue.filter((q) => q.id !== item.id) },
        rollbackOnError: true,
      },
    ).catch((e) => setActionError((e as ApiError).message));
  }

  async function openTranscript(student: StudentProgress) {
    setDrilldown({ student, lines: null });
    try {
      const lines = await api.transcript(sessionId, student.student_id);
      setDrilldown((d) => (d?.student.student_id === student.student_id ? { student, lines } : d));
    } catch (e) {
      setDrilldown(null);
      setActionError((e as ApiError).message);
    }
  }

  async function run(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
      await mutate();
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  async function setState(to: "open" | "paused" | "closed") {
    if (
      to === "closed" &&
      !window.confirm("End this lesson for the whole class? Students can't answer after this, and it can't be restarted.")
    ) {
      return;
    }
    try {
      await mutate(api.setSessionState(sessionId, to), { revalidate: false });
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  if (!me) return null;

  const studentFor = (id: string) => data?.progress.find((p) => p.student_id === id);

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        {!data && !error && <Skeleton label="Loading the lesson" rows={5} />}

        {data && (
          <>
            <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
              <div>
                <SubjectName subject={data.subject} />
                <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{data.title}</h1>
                <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <span className="font-semibold text-ink">{data.class_label}</span>
                  <span className="text-pencil">
                    {data.progress.length} student{data.progress.length === 1 ? "" : "s"}
                  </span>
                  {data.status === "paused" ? (
                    <span className="font-semibold text-amber">Paused</span>
                  ) : (
                    <TimeLeft closesAt={data.closes_at} status={data.status} />
                  )}
                </p>
              </div>
              {data.status === "scheduled" && (
                <Button onClick={() => run(() => api.startLesson(sessionId))}>Start lesson</Button>
              )}
              {(data.status === "open" || data.status === "paused") && (
                <div className="flex gap-2">
                  {data.status === "open" ? (
                    <Button variant="quiet" onClick={() => setState("paused")}>
                      Pause the class
                    </Button>
                  ) : (
                    <Button onClick={() => setState("open")}>Resume the class</Button>
                  )}
                  <Button variant="quiet" onClick={() => setState("closed")}>
                    End lesson
                  </Button>
                </div>
              )}
            </header>

            {data.status === "scheduled" && (
              <div className="mb-6">
                <Notice>
                  This lesson hasn&apos;t started. Starting it lets the class in, with the time limit
                  from the plan.
                </Notice>
              </div>
            )}
            {(data.status === "open" || data.status === "paused") && data.timeline.length > 1 && (
              <Phases
                timeline={data.timeline}
                current={data.phase_index}
                onMove={(index) => run(() => api.changePhase(sessionId, index))}
              />
            )}
            {data.status === "paused" && (
              <div className="mb-6">
                <Notice tone="amber">
                  The class is paused. Students can read their work but can&apos;t answer until you
                  resume.
                </Notice>
              </div>
            )}
            {data.status === "closed" && (
              <div className="mb-6">
                <Notice>
                  This lesson has ended. Students can no longer answer or ask for you.{" "}
                  <Link href={`/teacher/lessons/${sessionId}/review`} className="font-semibold underline underline-offset-4">
                    Review each student&apos;s work
                  </Link>
                </Notice>
              </div>
            )}

            {/* minmax(0, …) on both layouts: a grid track otherwise grows to
                fit the register's minimum width, pushing the page sideways on a
                phone instead of letting the register scroll inside its sheet. */}
            <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
              <NeedsYou
                queue={data.queue}
                onLook={(item) => {
                  const s = studentFor(item.student_id);
                  if (s) openTranscript(s);
                }}
                onDone={acknowledge}
              />
              <div className="space-y-6">
                <Register data={data} onOpen={openTranscript} openId={drilldown?.student.student_id} />
                {data.item_list.some((i) => i.kind === "written_response") && (
                  <ScoresToConfirm sessionId={sessionId} onConfirmed={() => mutate()} />
                )}
              </div>
            </div>
          </>
        )}
      </main>

      {drilldown && data && (
        <StudentSheet
          sessionId={sessionId}
          drilldown={drilldown}
          rungs={data.rungs}
          canMessage={data.status !== "closed"}
          onClose={() => setDrilldown(null)}
          onSent={() => openTranscript(drilldown.student)}
        />
      )}
    </>
  );
}

/* ---------- Needs you ---------- */

function NeedsYou({
  queue,
  onLook,
  onDone,
}: {
  queue: QueueItem[];
  onLook: (item: QueueItem) => void;
  onDone: (item: QueueItem) => void;
}) {
  return (
    <section
      aria-labelledby="needs-you"
      className={`rounded-[var(--radius-sheet)] border bg-sheet ${queue.length ? "border-red-pen/50" : "border-rule"}`}
    >
      <header className="flex items-baseline justify-between px-5 pt-4 pb-3">
        <h2 id="needs-you" className="text-base font-bold text-ink">
          Needs you
        </h2>
        <span
          aria-live="polite"
          className={`figures text-sm font-bold ${queue.length ? "text-red-pen" : "text-pencil"}`}
        >
          {queue.length === 0 ? "Nobody" : queue.length}
        </span>
      </header>

      {queue.length === 0 ? (
        <p className="flex items-center gap-2 px-5 pb-5 text-sm text-pencil">
          <Tick className="size-4" />
          The class is working. You&apos;ll see anyone who needs you here.
        </p>
      ) : (
        <ul role="list" className="border-t border-rule">
          {queue.map((item) => (
            <li
              key={item.id}
              className="border-b border-rule px-5 py-3 last:border-b-0"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="figures font-bold text-ink">{item.pseudonym}</span>
                <span className="figures text-xs text-faint">{clockTime(item.created_at)}</span>
              </div>
              <QueueKind kind={item.kind} priority={item.priority} />
              <p className="mt-1 text-sm text-ink">{item.summary}</p>
              <div className="mt-2.5 flex gap-2">
                <Button size="sm" variant="quiet" onClick={() => onLook(item)}>
                  See their work
                </Button>
                <Button variant="plain" onClick={() => onDone(item)}>
                  Mark as dealt with
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ---------- The register ---------- */

function Register({
  data,
  onOpen,
  openId,
}: {
  data: Console;
  onOpen: (student: StudentProgress) => void;
  openId?: string;
}) {
  return (
    <section aria-labelledby="register" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <header className="flex flex-wrap items-baseline justify-between gap-3 px-5 pt-4 pb-3">
        <h2 id="register" className="text-base font-bold text-ink">
          Register
        </h2>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-pencil">
          <span className="inline-flex items-center gap-1.5">
            <Tick className="size-3.5" /> right
          </span>
          <span className="inline-flex items-center gap-1.5">
            <LadderGauge rungs={data.rungs} reached={data.rungs[3] ?? null} /> help given so far
          </span>
        </p>
      </header>

      {data.progress.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-pencil">No students have been admitted to this lesson.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] border-t border-rule text-sm">
            <thead>
              <tr className="text-left text-xs text-pencil">
                <th scope="col" className="py-2.5 pr-3 pl-5 font-semibold">
                  Student
                </th>
                {data.item_list.map((item) => (
                  <th
                    key={item.id}
                    scope="col"
                    title={item.prompt}
                    className="px-2 py-2.5 text-center font-semibold"
                  >
                    {item.kind === "written_response" ? `Task ${item.ordinal}` : `Q${item.ordinal}`}
                  </th>
                ))}
                <th scope="col" className="py-2.5 pr-5 pl-2 text-right font-semibold">
                  {data.item_list.every((i) => i.kind === "written_response") ? "Handed in" : "Right"}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.progress.map((student) => (
                <tr
                  key={student.student_id}
                  className={`border-t border-rule ${openId === student.student_id ? "bg-sunken" : "hover:bg-paper"}`}
                >
                  <th scope="row" className="py-0 pr-3 pl-5 text-left font-normal">
                    <button
                      onClick={() => onOpen(student)}
                      className="flex min-h-12 w-full items-center gap-2 text-left"
                    >
                      <span className="figures font-bold text-ink underline decoration-transparent underline-offset-4 hover:decoration-ink">
                        {student.pseudonym}
                      </span>
                      {student.needs_you && (
                        <span className="text-xs font-bold whitespace-nowrap text-red-pen">needs you</span>
                      )}
                    </button>
                  </th>
                  {student.cells.map((cell) => (
                    <td key={cell.item_id} className="px-2 text-center">
                      <Cell cell={cell} rungs={data.rungs} />
                    </td>
                  ))}
                  <td className="figures pr-5 pl-2 text-right text-ink">
                    <span className="font-bold">{student.correct}</span>
                    <span className="text-pencil">/{data.items}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Cell({ cell, rungs }: { cell: StudentProgress["cells"][number]; rungs: string[] }) {
  if (cell.kind === "written_response") return <WrittenCell cell={cell} rungs={rungs} />;
  const tries = `${cell.attempts} ${cell.attempts === 1 ? "try" : "tries"}`;
  if (cell.solved) {
    return (
      <span className="inline-flex items-center justify-center" title={`Right after ${tries}`}>
        <Tick className="size-5" />
        <span className="sr-only">Right after {tries}</span>
      </span>
    );
  }
  if (cell.attempts === 0) {
    return (
      <span className="text-rule-strong" title="Not started">
        <span aria-hidden>–</span>
        <span className="sr-only">Not started</span>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-col items-center gap-0.5">
      <LadderGauge rungs={rungs} reached={cell.rung} />
      <span className="figures text-[11px] leading-none text-faint">{tries}</span>
    </span>
  );
}

function WrittenCell({ cell, rungs }: { cell: StudentProgress["cells"][number]; rungs: string[] }) {
  const words = `${cell.words} word${cell.words === 1 ? "" : "s"}`;
  if (cell.submitted) {
    const label =
      cell.score === null
        ? "Handed in, no score yet"
        : `${cell.score}/${cell.score_out_of}${cell.score_confirmed ? "" : " suggested"}`;
    return (
      <span className="inline-flex flex-col items-center gap-0.5" title={`${label}, ${words}`}>
        {cell.score !== null ? (
          <span className={`figures text-sm font-bold ${cell.score_confirmed ? "text-tick" : "text-amber"}`}>
            {cell.score}
            <span className="font-normal text-pencil">/{cell.score_out_of}</span>
          </span>
        ) : (
          <Tick className="size-5" />
        )}
        <span className="text-[11px] leading-none text-faint">
          {cell.score_confirmed ? "marked" : "to confirm"}
        </span>
      </span>
    );
  }
  if (cell.words === 0 && cell.attempts === 0) {
    return (
      <span className="text-rule-strong" title="Not started">
        <span aria-hidden>–</span>
        <span className="sr-only">Not started</span>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-col items-center gap-0.5" title={`Writing, ${words}`}>
      {cell.rung ? (
        <LadderGauge rungs={rungs} reached={cell.rung} />
      ) : (
        <span className="text-xs text-pencil">writing</span>
      )}
      <span className="figures text-[11px] leading-none text-faint">{words}</span>
    </span>
  );
}

/* ---------- Lesson phases ---------- */

function Phases({
  timeline,
  current,
  onMove,
}: {
  timeline: Phase[];
  current: number;
  onMove: (index: number) => void;
}) {
  const next = current + 1 < timeline.length ? timeline[current + 1] : null;
  return (
    <section
      aria-label="Lesson phases"
      className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-3"
    >
      <ol role="list" className="flex flex-wrap items-center gap-x-1 gap-y-2 text-sm">
        {timeline.map((phase, i) => (
          <li key={`${phase.name}-${i}`} className="flex items-center gap-1">
            {i > 0 && (
              <span aria-hidden className="px-1 text-faint">
                →
              </span>
            )}
            <button
              onClick={() => i !== current && onMove(i)}
              aria-current={i === current ? "step" : undefined}
              className={`rounded-full px-3 py-1 ${
                i === current
                  ? "bg-ink font-semibold text-white"
                  : "text-pencil hover:bg-sunken hover:text-ink"
              }`}
              title={`${phase.minutes} min, tutors ${phase.tutors_on ? "on" : "off"}`}
            >
              {phase.name}
              <span className={`ml-1.5 text-xs ${i === current ? "text-white/80" : "text-faint"}`}>
                {phase.tutors_on ? "tutors on" : "tutors off"}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {next && (
        <Button size="sm" onClick={() => onMove(current + 1)}>
          Next: {next.name}
        </Button>
      )}
    </section>
  );
}

/* ---------- Scores the AI suggested, waiting for the teacher ---------- */

function ScoresToConfirm({ sessionId, onConfirmed }: { sessionId: string; onConfirmed: () => void }) {
  const { data, error, mutate } = useSWR<Score[]>(["scores", sessionId], () => api.scores(sessionId), {
    refreshInterval: POLL_MS * 2,
  });
  const [openId, setOpenId] = useState<string | null>(null);

  const waiting = data?.filter((s) => s.status === "suggested") ?? [];
  const marked = data?.filter((s) => s.status === "confirmed") ?? [];

  return (
    <section aria-labelledby="scores" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <header className="flex flex-wrap items-baseline justify-between gap-3 px-5 pt-4 pb-3">
        <div>
          <h2 id="scores" className="text-base font-bold text-ink">
            Scores to confirm
          </h2>
          <p className="text-xs text-pencil">
            The tutor suggests a score. Students only see it after you confirm or change it.
          </p>
        </div>
        <span className={`figures text-sm font-bold ${waiting.length ? "text-amber" : "text-pencil"}`}>
          {data ? (waiting.length === 0 ? "None waiting" : waiting.length) : ""}
        </span>
      </header>
      {error && (
        <div className="px-5 pb-4">
          <ErrorNote>{(error as ApiError).message}</ErrorNote>
        </div>
      )}
      {data && data.length === 0 && (
        <p className="px-5 pb-5 text-sm text-pencil">Nothing handed in yet.</p>
      )}
      {data && data.length > 0 && (
        <ul role="list" className="border-t border-rule">
          {[...waiting, ...marked].map((score) => (
            <li key={score.id} className="border-b border-rule last:border-b-0">
              <button
                onClick={() => setOpenId(openId === score.id ? null : score.id)}
                aria-expanded={openId === score.id}
                className="flex w-full flex-wrap items-baseline justify-between gap-3 px-5 py-3 text-left hover:bg-paper"
              >
                <span className="text-sm">
                  <span className="figures font-bold text-ink">{score.pseudonym}</span>
                  <span className="ml-2 text-pencil">Task {score.item_ordinal}</span>
                </span>
                <span className="figures text-sm">
                  {score.status === "confirmed" ? (
                    <span className="font-semibold text-tick">
                      {score.confirmed_total}/{score.out_of} confirmed
                    </span>
                  ) : (
                    <span className="font-semibold text-amber">
                      {score.suggested_total}/{score.out_of} suggested
                    </span>
                  )}
                </span>
              </button>
              {openId === score.id && (
                <ConfirmScore
                  score={score}
                  onDone={async () => {
                    await mutate();
                    onConfirmed();
                    setOpenId(null);
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ConfirmScore({ score, onDone }: { score: Score; onDone: () => void }) {
  const source = score.confirmed ?? score.suggested;
  const [points, setPoints] = useState<Record<string, number>>(
    Object.fromEntries(source.criteria.map((c) => [c.name, c.points])),
  );
  const [comment, setComment] = useState(score.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = Object.values(points).reduce((a, b) => a + b, 0);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.confirmScore(score.id, points, comment);
      onDone();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 bg-paper px-5 py-4 text-sm">
      <div>
        <p className="text-xs font-semibold text-pencil">{score.prompt}</p>
        <p className="mt-1 rounded-[var(--radius-control)] border border-rule bg-sheet px-3 py-2 font-serif text-base leading-7 whitespace-pre-line text-ink">
          {score.text}
        </p>
      </div>

      <table className="w-full text-left">
        <thead>
          <tr className="text-xs text-pencil">
            <th scope="col" className="pb-1 font-semibold">
              Area
            </th>
            <th scope="col" className="pb-1 font-semibold">
              Tutor&apos;s reason
            </th>
            <th scope="col" className="pb-1 text-right font-semibold">
              Points
            </th>
          </tr>
        </thead>
        <tbody>
          {score.suggested.criteria.map((c) => (
            <tr key={c.name} className="border-t border-rule align-top">
              <th scope="row" className="py-2 pr-3 font-semibold text-ink">
                {c.name}
              </th>
              <td className="py-2 pr-3 text-pencil">{c.reason}</td>
              <td className="py-2 text-right whitespace-nowrap">
                <label className="sr-only" htmlFor={`${score.id}-${c.name}`}>
                  {c.name} points
                </label>
                <input
                  id={`${score.id}-${c.name}`}
                  type="number"
                  min={0}
                  max={c.max}
                  value={points[c.name] ?? 0}
                  onChange={(e) =>
                    setPoints((p) => ({
                      ...p,
                      [c.name]: Math.max(0, Math.min(c.max, Number(e.target.value) || 0)),
                    }))
                  }
                  className="figures h-8 w-14 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-right text-ink focus:border-ink focus:outline-none"
                />
                <span className="figures ml-1 text-pencil">/{c.max}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {(score.suggested.keep || score.suggested.develop.length > 0) && (
        <div className="text-pencil">
          {score.suggested.keep && <p>Went well: {score.suggested.keep}</p>}
          {score.suggested.develop.length > 0 && <p>To work on: {score.suggested.develop.join(" ")}</p>}
        </div>
      )}

      <div>
        <label htmlFor={`${score.id}-comment`} className="font-semibold text-ink">
          Your comment <span className="font-normal text-faint">(optional, the student sees it)</span>
        </label>
        <textarea
          id={`${score.id}-comment`}
          rows={2}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          className="mt-1 block w-full resize-none rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 py-2 text-ink focus:border-ink focus:outline-none"
        />
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="figures font-semibold text-ink">
          Total {total}/{score.out_of}
        </span>
        <Button onClick={confirm} disabled={busy}>
          {busy ? "Saving…" : score.status === "confirmed" ? "Update score" : "Confirm score"}
        </Button>
      </div>
    </div>
  );
}

/* ---------- One student's work, beside the register ---------- */

function StudentSheet({
  sessionId,
  drilldown,
  rungs,
  canMessage,
  onClose,
  onSent,
}: {
  sessionId: string;
  drilldown: Drilldown;
  rungs: string[];
  canMessage: boolean;
  onClose: () => void;
  onSent: () => void;
}) {
  const { student, lines } = drilldown;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The console re-renders on every poll, handing down a new `onClose` each
  // time. Keep the latest in a ref so focus moves only when a different
  // student is opened - not every four seconds, out of the note being typed.
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  useEffect(() => {
    headingRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [student.student_id]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!note.trim()) return;
    setSending(true);
    setError(null);
    try {
      await api.messageStudent(sessionId, student.student_id, note.trim());
      setNote("");
      setSent(true);
      onSent();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-30 bg-ink/20 lg:hidden" />
      <aside
        role="dialog"
        aria-labelledby="sheet-title"
        className="slide-in fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-rule bg-sheet shadow-[-24px_0_48px_-32px_rgba(31,42,68,0.45)]"
      >
        <header className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
          <div>
            <h2
              id="sheet-title"
              ref={headingRef}
              tabIndex={-1}
              className="figures text-lg font-bold text-ink focus:outline-none"
            >
              {student.pseudonym}
            </h2>
            <p className="text-xs text-pencil">
              Opening this is recorded, and students are told their teacher can read their work.
            </p>
          </div>
          <Button variant="plain" onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {lines === null && <Skeleton label="Loading their work" rows={4} />}
          {lines?.length === 0 && <p className="text-sm text-pencil">Nothing yet. They haven&apos;t answered anything.</p>}
          {lines && lines.length > 0 && (
            <ol role="list" className="space-y-3">
              {lines.map((line) => (
                <li key={line.record_id} className="flex gap-3 text-sm">
                  <span className="figures w-11 shrink-0 pt-0.5 text-xs whitespace-nowrap text-faint">
                    {clockTime(line.created_at)}
                  </span>
                  <TranscriptEntry line={line} rungs={rungs} />
                </li>
              ))}
            </ol>
          )}
        </div>

        {canMessage && (
          <form onSubmit={send} className="border-t border-rule px-5 py-4">
            <label htmlFor="note" className="text-sm font-bold text-ink">
              Send {student.pseudonym} a note
            </label>
            <textarea
              id="note"
              rows={2}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setSent(false);
              }}
              placeholder="It appears on their screen."
              className="mt-1.5 block w-full resize-none rounded-[var(--radius-control)] border border-rule-strong px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-ink focus:outline-none"
            />
            {error && (
              <div className="mt-2">
                <ErrorNote>{error}</ErrorNote>
              </div>
            )}
            <div className="mt-2 flex items-center justify-between gap-3">
              <span aria-live="polite" className="text-xs text-tick">
                {sent ? "Sent" : ""}
              </span>
              <Button type="submit" size="sm" disabled={sending || !note.trim()}>
                {sending ? "Sending…" : "Send note"}
              </Button>
            </div>
          </form>
        )}
      </aside>
    </>
  );
}

function TranscriptEntry({ line, rungs }: { line: TranscriptLine; rungs: string[] }) {
  const detail = line.detail;
  if (line.kind === "attempt") {
    return (
      <span className="flex flex-wrap items-center gap-2 text-ink">
        Answered <span className="font-bold">{String(detail.answer ?? "")}</span>
        {line.correct ? (
          <span className="inline-flex items-center gap-1 text-tick">
            <Tick className="size-4" /> right
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-pencil">
            <Cross className="size-3.5" /> not yet
          </span>
        )}
      </span>
    );
  }
  if (line.kind === "hint") {
    const rung = String(detail.rung ?? "");
    return (
      <span className="block min-w-0 flex-1 rounded-[var(--radius-control)] bg-sunken px-3 py-2">
        <span className="mb-1 flex items-center gap-2 text-xs font-semibold text-pencil">
          <LadderGauge rungs={rungs} reached={rung || null} />
          Tutor: {(RUNG_WORDS[rung] ?? "help").toLowerCase()}
        </span>
        <span className="block text-ink">{String(detail.message ?? "")}</span>
      </span>
    );
  }
  if (line.kind === "teacher_feedback") {
    return (
      <span className="block min-w-0 flex-1 rounded-[var(--radius-control)] border border-rule px-3 py-2 text-ink">
        <span className="block text-xs font-semibold text-pencil">Your note</span>
        {String(detail.text ?? "")}
      </span>
    );
  }
  if (line.kind === "tutor_request") {
    const asked = String(detail.question || ASK_WORDS[String(detail.ask)] || detail.ask || "");
    return (
      <span className="text-ink">
        Asked the tutor: <span className="font-semibold">{asked}</span>
        <span className="figures ml-2 text-xs text-faint">{String(detail.words ?? 0)} words written</span>
      </span>
    );
  }
  if (line.kind === "submission") {
    return (
      <span className="block min-w-0 flex-1">
        <span className="block font-semibold text-tick">Handed in</span>
        <span className="mt-1 block rounded-[var(--radius-control)] border border-rule px-3 py-2 font-serif whitespace-pre-line text-ink">
          {String(detail.text ?? "")}
        </span>
      </span>
    );
  }
  if (line.kind === "draft") {
    return (
      <span className="figures text-pencil">Saved their writing, {String(detail.words ?? 0)} words</span>
    );
  }
  if (detail.event === "requested_teacher") {
    return <span className="font-bold text-red-pen">Asked for you</span>;
  }
  return <span className="text-pencil">{line.kind.replace(/_/g, " ")}</span>;
}
