"use client";

import Link from "next/link";
import useSWR from "swr";
import { agentApi, ApiError, type LearnCard } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { ErrorNote, Skeleton, SubjectName, TimeLeft } from "@/components/ui";

export default function StudentLessons() {
  const me = useSignedIn("student");
  // Refreshes, so a lesson the teacher starts appears without a reload.
  const { data: lessons, error } = useSWR<LearnCard[]>(
    me ? "student-lessons" : null,
    agentApi.myLessons,
    { refreshInterval: 10000 },
  );

  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <PageTitle lede="Carry on where you left off, or look back at one that's over.">
          Your lessons
        </PageTitle>

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !lessons && <Skeleton label="Loading your lessons" rows={2} />}
        {lessons?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5 py-8 text-pencil">
            <p className="font-semibold text-ink">No lessons are open right now.</p>
            <p className="mt-1 text-sm">
              When your teacher starts one, it appears here by itself. There&apos;s no need to
              refresh.
            </p>
          </div>
        )}
        {lessons && lessons.length > 0 && (
          <ul role="list" className="space-y-3">
            {lessons.map((l) => (
              <li key={l.session_id}>
                <Link
                  href={`/student/${l.session_id}`}
                  className="flex items-center gap-4 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4 transition-colors hover:border-ink"
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <SubjectName subject={l.subject} />
                    <span className="font-serif text-lg font-semibold text-ink">{l.title}</span>
                    <span className="flex flex-wrap gap-x-4 text-sm">
                      {l.status === "closed" ? (
                        <span className="text-pencil">Over</span>
                      ) : l.completed ? (
                        <span className="font-semibold text-tick">Finished</span>
                      ) : (
                        <span className="text-pencil">{l.steps} parts</span>
                      )}
                      {l.status === "paused" ? (
                        <span className="font-semibold text-amber">Paused</span>
                      ) : l.status === "closed" ? (
                        l.result && (
                          <span className="figures font-semibold text-ink">
                            {l.result.total} / {l.result.out_of}
                          </span>
                        )
                      ) : (
                        <TimeLeft closesAt={l.closes_at} status={l.status} />
                      )}
                    </span>
                  </span>
                  <span className="self-center text-sm font-semibold text-ink">
                    {l.status === "closed" ? "Look back" : "Open"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
