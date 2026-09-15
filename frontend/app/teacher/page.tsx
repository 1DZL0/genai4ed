"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, ApiError, type LessonSummary, type Today } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Button, clockTime, Empty, ErrorNote, Skeleton, SubjectName, TimeLeft } from "@/components/ui";

const linkButton =
  "inline-flex h-10 items-center rounded-[var(--radius-control)] px-4 text-sm font-semibold";

export default function TeacherToday() {
  const router = useRouter();
  const me = useSignedIn("teacher");
  const [starting, setStarting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error } = useSWR<Today>(me ? "teacher-today" : null, api.today, {
    refreshInterval: 15000,
  });

  if (!me) return null;

  const running = data?.coming_up.filter((l) => l.status !== "scheduled") ?? [];
  const booked = data?.coming_up.filter((l) => l.status === "scheduled") ?? [];
  const waiting = running.reduce((n, l) => n + l.open_exceptions, 0);

  async function start(lesson: LessonSummary) {
    setStarting(lesson.lesson_id);
    setActionError(null);
    try {
      await api.startLesson(lesson.lesson_id);
      router.push(`/teacher/${lesson.lesson_id}`);
    } catch (e) {
      setActionError((e as ApiError).message);
      setStarting(null);
    }
  }

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
        <PageTitle
          lede={data ? summary(running.length, booked.length, waiting) : undefined}
          actions={
            <>
              <Link
                href="/teacher/contracts"
                className={`${linkButton} border border-rule-strong bg-sheet text-ink hover:border-ink`}
              >
                Lesson plans
              </Link>
              <Link href="/teacher/new" className={`${linkButton} bg-ink text-white hover:bg-ink-hover`}>
                Write a lesson plan
              </Link>
            </>
          }
        >
          Today
        </PageTitle>

        {(error || actionError) && (
          <div className="mb-4">
            <ErrorNote>{actionError ?? (error as ApiError).message}</ErrorNote>
          </div>
        )}
        {!error && !data && <Skeleton label="Loading today's lessons" rows={3} />}

        {data && (
          <div className="space-y-10">
            <section aria-labelledby="running">
              <h2 id="running" className="mb-3 text-base font-bold text-ink">
                Running now
              </h2>
              {running.length === 0 ? (
                <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5">
                  <Empty>No lesson is running. Start one from the list below when your class is ready.</Empty>
                </div>
              ) : (
                <ul role="list" className="grid gap-3 md:grid-cols-2">
                  {running.map((l) => (
                    <li key={l.lesson_id}>
                      <LessonCard lesson={l} href={`/teacher/${l.lesson_id}`}>
                        {l.status === "paused" ? (
                          <span className="font-semibold text-amber">Paused</span>
                        ) : (
                          <TimeLeft closesAt={l.closes_at} status={l.status} />
                        )}
                        {l.phase_name && (
                          <span className="text-pencil">
                            {l.phase_name}
                            {l.tutors_on ? ", tutors on" : ", tutors off"}
                          </span>
                        )}
                        {l.open_exceptions > 0 && (
                          <span className="font-bold text-red-pen">
                            {l.open_exceptions} {l.open_exceptions === 1 ? "needs" : "need"} you
                          </span>
                        )}
                      </LessonCard>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="booked">
              <h2 id="booked" className="mb-3 text-base font-bold text-ink">
                Coming up
              </h2>
              {booked.length === 0 ? (
                <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5">
                  <Empty
                    action={
                      <Link
                        href="/teacher/contracts"
                        className="text-sm font-semibold text-ink underline underline-offset-4"
                      >
                        Use a lesson plan with a class
                      </Link>
                    }
                  >
                    Nothing else booked for today.
                  </Empty>
                </div>
              ) : (
                <ul role="list" className="space-y-3">
                  {booked.map((l) => (
                    <li
                      key={l.lesson_id}
                      className="flex flex-wrap items-center gap-4 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4"
                    >
                      <div className="min-w-0 flex-1">
                        <SubjectName subject={l.subject} />
                        <p className="mt-1 font-serif text-lg leading-snug font-semibold text-ink">{l.title}</p>
                        <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                          <span className="font-semibold text-ink">{l.class_label}</span>
                          <span className="text-pencil">
                            {l.students} student{l.students === 1 ? "" : "s"}
                          </span>
                          <span className="text-pencil">
                            {l.items} task{l.items === 1 ? "" : "s"}
                          </span>
                          {l.scheduled_for && (
                            <span className="figures text-pencil">{clockTime(l.scheduled_for)}</span>
                          )}
                        </p>
                      </div>
                      <Button onClick={() => start(l)} disabled={starting !== null}>
                        {starting === l.lesson_id ? "Starting…" : "Start lesson"}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="finished">
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
                  <h2 id="finished" className="text-base font-bold text-ink">
                    Finished this week
                  </h2>
                  <Link
                    href="/teacher/lessons/past"
                    className="text-sm text-pencil underline underline-offset-4 hover:text-ink"
                  >
                    All past lessons
                  </Link>
                </div>
                {data.finished.length === 0 && (
                  <p className="text-sm text-pencil">No lessons have ended this week.</p>
                )}
                <ul role="list" className="grid gap-3 md:grid-cols-2">
                  {data.finished.map((l) => (
                    <li key={l.lesson_id}>
                      <LessonCard lesson={l} href={`/teacher/lessons/${l.lesson_id}/review`} quiet>
                        {l.closed_at && (
                          <span className="text-pencil">
                            Ended {new Date(l.closed_at).toLocaleDateString([], { weekday: "short" })}{" "}
                            <span className="figures">{clockTime(l.closed_at)}</span>
                          </span>
                        )}
                        {l.scores_to_confirm > 0 && (
                          <span className="font-bold text-amber">
                            {l.scores_to_confirm} score{l.scores_to_confirm === 1 ? "" : "s"} to confirm
                          </span>
                        )}
                      </LessonCard>
                    </li>
                  ))}
                </ul>
              </section>
          </div>
        )}
      </main>
    </>
  );
}

function summary(running: number, booked: number, waiting: number) {
  const parts = [
    running === 0 ? "No lessons running" : `${running} lesson${running === 1 ? "" : "s"} running`,
    booked > 0 ? `${booked} still to start` : null,
  ].filter(Boolean);
  const lead = parts.join(", ");
  if (waiting === 0) return `${lead}. Nobody needs you right now.`;
  return `${lead}. ${waiting} ${waiting === 1 ? "thing needs" : "things need"} you.`;
}

function LessonCard({
  lesson,
  href,
  quiet = false,
  children,
}: {
  lesson: LessonSummary;
  href: string;
  quiet?: boolean;
  children: React.ReactNode;
}) {
  const waiting = !quiet && lesson.open_exceptions > 0;
  return (
    <Link
      href={href}
      className={`flex h-full rounded-[var(--radius-sheet)] border bg-sheet px-5 py-4 transition-colors hover:border-ink ${
        waiting ? "border-red-pen/60" : "border-rule"
      }`}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <SubjectName subject={lesson.subject} />
        <span className="font-serif text-lg leading-snug font-semibold text-ink">{lesson.title}</span>
        <span className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 pt-2 text-sm">
          <span className="font-semibold text-ink">{lesson.class_label}</span>
          {children}
        </span>
      </span>
    </Link>
  );
}
