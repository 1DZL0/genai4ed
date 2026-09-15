"use client";

import Link from "next/link";
import useSWR from "swr";
import { api, ApiError, type TeacherSessionSummary } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Empty, ErrorNote, Skeleton, SubjectName, TimeLeft } from "@/components/ui";

const linkButton =
  "inline-flex h-10 items-center rounded-[var(--radius-control)] px-4 text-sm font-semibold";

export default function TeacherDashboard() {
  const me = useSignedIn("teacher");
  const { data: sessions, error } = useSWR<TeacherSessionSummary[]>(
    me ? "teacher-sessions" : null,
    api.teacherSessions,
    { refreshInterval: 15000 },
  );

  if (!me) return null;

  const live = sessions?.filter((s) => s.status !== "closed") ?? [];
  const ended = sessions?.filter((s) => s.status === "closed") ?? [];
  const waiting = live.reduce((n, s) => n + s.open_exceptions, 0);

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
        <PageTitle
          lede={sessions ? summary(live.length, waiting) : undefined}
          actions={
            <>
              <Link
                href="/teacher/contracts"
                className={`${linkButton} border border-rule-strong bg-sheet text-ink hover:border-ink`}
              >
                Start a lesson
              </Link>
              <Link href="/teacher/new" className={`${linkButton} bg-ink text-white hover:bg-ink-hover`}>
                Write a lesson
              </Link>
            </>
          }
        >
          Dashboard
        </PageTitle>

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !sessions && <Skeleton label="Loading your lessons" rows={3} />}

        {sessions && (
          <div className="space-y-10">
            <section aria-labelledby="live">
              <h2 id="live" className="mb-3 text-base font-bold text-ink">
                Running now
              </h2>
              {live.length === 0 ? (
                <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5">
                  <Empty
                    action={
                      <Link
                        href="/teacher/contracts"
                        className="text-sm font-semibold text-ink underline underline-offset-4"
                      >
                        Start one of your lessons
                      </Link>
                    }
                  >
                    No lesson is running.
                  </Empty>
                </div>
              ) : (
                <SessionList sessions={live} />
              )}
            </section>

            {ended.length > 0 && (
              <section aria-labelledby="ended">
                <h2 id="ended" className="mb-3 text-base font-bold text-ink">
                  Ended
                </h2>
                <SessionList sessions={ended} quiet />
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}

function summary(running: number, waiting: number) {
  const lessons =
    running === 0 ? "No lessons running" : `${running} lesson${running === 1 ? "" : "s"} running`;
  if (waiting === 0) return `${lessons}. Nobody needs you right now.`;
  return `${lessons}. ${waiting} ${waiting === 1 ? "thing needs" : "things need"} you.`;
}

function SessionList({ sessions, quiet = false }: { sessions: TeacherSessionSummary[]; quiet?: boolean }) {
  return (
    <ul role="list" className="grid gap-3 md:grid-cols-2">
      {sessions.map((s) => {
        const waiting = !quiet && s.open_exceptions > 0;
        return (
          <li key={s.session_id}>
            <Link
              href={`/teacher/${s.session_id}`}
              className={`flex h-full rounded-[var(--radius-sheet)] border bg-sheet px-5 py-4 transition-colors hover:border-ink ${
                waiting ? "border-red-pen/60" : "border-rule"
              } ${quiet ? "opacity-80 hover:opacity-100" : ""}`}
            >
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <SubjectName subject={s.subject} />
                <span className="font-serif text-lg leading-snug font-semibold text-ink">{s.title}</span>
                <span className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 pt-2 text-sm">
                  <span className="font-semibold text-ink">{s.class_label}</span>
                  {s.status === "paused" ? (
                    <span className="font-semibold text-amber">Paused</span>
                  ) : (
                    <TimeLeft closesAt={s.closes_at} status={s.status} />
                  )}
                  {waiting && (
                    <span className="font-bold text-red-pen">
                      {s.open_exceptions} {s.open_exceptions === 1 ? "needs" : "need"} you
                    </span>
                  )}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
