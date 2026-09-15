"use client";

import Link from "next/link";
import useSWR from "swr";
import { api, ApiError, type SessionSummary } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { ErrorNote, Skeleton, SubjectName, TimeLeft } from "@/components/ui";

export default function StudentSessions() {
  const me = useSignedIn("student");
  // Refreshes, so a lesson the teacher starts appears without a reload.
  const { data: sessions, error } = useSWR<SessionSummary[]>(
    me ? "student-sessions" : null,
    api.mySessions,
    { refreshInterval: 10000 },
  );

  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <PageTitle lede="Pick a lesson to carry on where you left off.">Your lessons</PageTitle>

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !sessions && <Skeleton label="Loading your lessons" rows={2} />}
        {sessions?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5 py-8 text-pencil">
            <p className="font-semibold text-ink">No lessons are open right now.</p>
            <p className="mt-1 text-sm">
              When your teacher starts one, it appears here by itself. There&apos;s no need to
              refresh.
            </p>
          </div>
        )}
        {sessions && sessions.length > 0 && (
          <ul role="list" className="space-y-3">
            {sessions.map((s) => (
              <li key={s.session_id}>
                <Link
                  href={`/student/${s.session_id}`}
                  className="flex items-center gap-4 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4 transition-colors hover:border-ink"
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <SubjectName subject={s.subject} />
                    <span className="font-serif text-lg font-semibold text-ink">{s.title}</span>
                    <span className="flex flex-wrap gap-x-4 text-sm">
                      <span className="text-pencil">
                        {s.items} question{s.items === 1 ? "" : "s"}
                      </span>
                      {s.status === "paused" ? (
                        <span className="font-semibold text-amber">Paused</span>
                      ) : (
                        <TimeLeft closesAt={s.closes_at} status={s.status} />
                      )}
                    </span>
                  </span>
                  <span className="self-center text-sm font-semibold text-ink">Open</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
