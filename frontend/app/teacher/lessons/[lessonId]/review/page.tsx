"use client";

import { use, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, ApiError, type Review, type StudentProgress, type StudentWork } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import {
  clockTime,
  Cross,
  ErrorNote,
  LadderGauge,
  RUNG_WORDS,
  Skeleton,
  SubjectName,
  Tick,
  Button,
} from "@/components/ui";

export default function LessonReview({ params }: PageProps<"/teacher/lessons/[lessonId]/review">) {
  const { lessonId } = use(params);
  const me = useSignedIn("teacher");
  const { data, error } = useSWR<Review>(me ? ["review", lessonId] : null, () => api.review(lessonId));
  const [chosen, setChosen] = useState<string | null>(null);

  if (!me) return null;

  const students = data?.progress ?? [];
  const selectedIndex = Math.max(0, students.findIndex((s) => s.student_id === chosen));
  const selected = students[selectedIndex];
  const written = data?.item_list.some((i) => i.kind === "written_response") ?? false;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!data && !error && <Skeleton label="Loading the lesson" rows={5} />}

        {data && (
          <>
            <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
              <div>
                <SubjectName subject={data.lesson.subject} />
                <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{data.lesson.title}</h1>
                <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <span className="font-semibold text-ink">{data.lesson.class_label}</span>
                  {data.lesson.closed_at ? (
                    <span className="text-pencil">
                      Ended {new Date(data.lesson.closed_at).toLocaleDateString()}{" "}
                      <span className="figures">{clockTime(data.lesson.closed_at)}</span>
                    </span>
                  ) : (
                    <span className="text-pencil">Still running</span>
                  )}
                  <span className="text-pencil">Plan version {data.lesson.plan_version}</span>
                </p>
              </div>
              <Link
                href={`/teacher/${lessonId}`}
                className="text-sm text-pencil underline underline-offset-4 hover:text-ink"
              >
                Open the lesson register
              </Link>
            </header>

            <dl className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Figure label="Students" value={data.students} />
              <Figure label="Started work" value={data.started} />
              <Figure
                label={written ? "Handed in everything" : "Got every question right"}
                value={data.finished_all}
              />
              <Figure label="Times they needed you" value={data.times_needed_you} />
            </dl>

            {data.lesson.scores_to_confirm > 0 && (
              <p className="mb-6 text-sm text-ink">
                <span className="font-bold text-amber">
                  {data.lesson.scores_to_confirm} score{data.lesson.scores_to_confirm === 1 ? "" : "s"} still to confirm.
                </span>{" "}
                <Link href={`/teacher/${lessonId}`} className="underline underline-offset-4">
                  Confirm them on the register
                </Link>
              </p>
            )}

            {students.length === 0 ? (
              <p className="text-sm text-pencil">No students were admitted to this lesson.</p>
            ) : (
              <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
                <nav aria-label="Students" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
                  <ul role="list" className="max-h-[32rem] overflow-y-auto py-1">
                    {students.map((s) => (
                      <li key={s.student_id}>
                        <button
                          onClick={() => setChosen(s.student_id)}
                          aria-current={s.student_id === selected?.student_id ? "true" : undefined}
                          className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-sm ${
                            s.student_id === selected?.student_id ? "bg-sunken" : "hover:bg-paper"
                          }`}
                        >
                          <span
                            className={`figures font-bold text-ink ${
                              s.student_id === selected?.student_id ? "underline underline-offset-4" : ""
                            }`}
                          >
                            {s.pseudonym}
                          </span>
                          <span className="figures text-xs text-pencil">{summaryFor(s, written)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </nav>

                {selected && (
                  <StudentPanel
                    key={selected.student_id}
                    lessonId={lessonId}
                    student={selected}
                    rungs={data.rungs}
                    onPrevious={
                      selectedIndex > 0 ? () => setChosen(students[selectedIndex - 1].student_id) : undefined
                    }
                    onNext={
                      selectedIndex < students.length - 1
                        ? () => setChosen(students[selectedIndex + 1].student_id)
                        : undefined
                    }
                  />
                )}
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3">
      <dt className="text-xs text-pencil">{label}</dt>
      <dd className="figures font-serif text-2xl font-semibold text-ink">{value}</dd>
    </div>
  );
}

function summaryFor(s: StudentProgress, written: boolean) {
  if (written) {
    const handed = s.cells.filter((c) => c.submitted).length;
    return `${handed}/${s.cells.length} handed in`;
  }
  return `${s.correct}/${s.cells.length} right`;
}

function StudentPanel({
  lessonId,
  student,
  rungs,
  onPrevious,
  onNext,
}: {
  lessonId: string;
  student: StudentProgress;
  rungs: string[];
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  const { data, error } = useSWR<StudentWork>(["student-work", lessonId, student.student_id], () =>
    api.studentWork(lessonId, student.student_id),
  );

  return (
    <section aria-labelledby="student-name" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-4">
        <div>
          <h2 id="student-name" className="figures text-lg font-bold text-ink">
            {student.pseudonym}
          </h2>
          <p className="text-xs text-pencil">Opening a student&apos;s work is recorded.</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="quiet" onClick={onPrevious} disabled={!onPrevious}>
            Previous
          </Button>
          <Button size="sm" variant="quiet" onClick={onNext} disabled={!onNext}>
            Next
          </Button>
        </div>
      </header>

      {error && (
        <div className="p-5">
          <ErrorNote>{(error as ApiError).message}</ErrorNote>
        </div>
      )}
      {!data && !error && (
        <div className="p-5">
          <Skeleton label="Loading their work" rows={3} />
        </div>
      )}

      {data && (
        <div className="space-y-6 px-5 py-5">
          {data.written.map((w) => (
            <article key={w.item_id}>
              <p className="text-xs font-semibold text-pencil">
                Task {w.ordinal}: {w.prompt}
              </p>
              {w.text ? (
                <p className="mt-2 rounded-[var(--radius-control)] border border-rule px-4 py-3 font-serif text-base leading-7 whitespace-pre-line text-ink">
                  {w.text}
                </p>
              ) : (
                <p className="mt-2 text-sm text-pencil">Nothing written.</p>
              )}
              <p className="mt-2 flex flex-wrap gap-x-4 text-sm">
                {w.submitted ? (
                  <span className="font-semibold text-tick">Handed in</span>
                ) : (
                  <span className="text-pencil">Not handed in</span>
                )}
                {w.score &&
                  (w.score.status === "confirmed" ? (
                    <span className="figures font-semibold text-ink">
                      Score {w.score.confirmed_total}/{w.score.out_of}
                    </span>
                  ) : (
                    <span className="figures font-semibold text-amber">
                      Suggested {w.score.suggested_total}/{w.score.out_of}, not confirmed
                    </span>
                  ))}
              </p>
              {w.score?.comment && <p className="mt-1 text-sm text-pencil">Your comment: {w.score.comment}</p>}
            </article>
          ))}

          <div>
            <h3 className="mb-2 text-sm font-bold text-ink">What happened</h3>
            {data.events.length === 0 ? (
              <p className="text-sm text-pencil">Nothing recorded.</p>
            ) : (
              <ol role="list" className="space-y-2.5">
                {data.events.map((e, i) => (
                  <li key={`${e.at}-${i}`} className="flex gap-3 text-sm">
                    <span className="figures w-11 shrink-0 pt-0.5 text-xs text-faint">{clockTime(e.at)}</span>
                    <EventLine event={e} rungs={rungs} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function EventLine({ event, rungs }: { event: StudentWork["events"][number]; rungs: string[] }) {
  const where = event.item_ordinal ? `Task ${event.item_ordinal}` : "";
  switch (event.kind) {
    case "attempt":
      return (
        <span className="flex flex-wrap items-center gap-2 text-ink">
          {where}: answered <span className="font-bold">{event.text}</span>
          {event.correct ? (
            <Tick className="size-4" />
          ) : (
            <Cross className="size-3.5" />
          )}
        </span>
      );
    case "hint":
      return (
        <span className="block min-w-0 flex-1 rounded-[var(--radius-control)] bg-sunken px-3 py-2">
          <span className="mb-1 flex items-center gap-2 text-xs font-semibold text-pencil">
            <LadderGauge rungs={rungs} reached={event.rung} />
            Tutor, {where}: {(RUNG_WORDS[event.rung ?? ""] ?? "help").toLowerCase()}
          </span>
          <span className="block text-ink">{event.text}</span>
        </span>
      );
    case "ask":
      return (
        <span className="text-ink">
          {where}: asked the tutor <span className="font-semibold">{event.text}</span>
        </span>
      );
    case "submitted":
      return <span className="font-semibold text-tick">{where}: handed in ({event.text})</span>;
    case "teacher_note":
      return <span className="text-ink">Your note: {event.text}</span>;
    default:
      return <span className="font-semibold text-red-pen">{event.text}</span>;
  }
}
