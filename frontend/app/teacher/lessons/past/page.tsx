"use client";

import Link from "next/link";
import useSWR from "swr";
import { api, ApiError, type LessonSummary } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { clockTime, Empty, ErrorNote, Skeleton, SubjectName } from "@/components/ui";

export default function PastLessons() {
  const me = useSignedIn("teacher");
  const { data, error } = useSWR<LessonSummary[]>(me ? "past-lessons" : null, api.pastLessons);

  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle lede="Every lesson that has ended, newest first. Open one to go through each student's work.">
          Past lessons
        </PageTitle>

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !data && <Skeleton label="Loading past lessons" rows={3} />}
        {data?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5">
            <Empty>No lessons have ended yet.</Empty>
          </div>
        )}
        {data && data.length > 0 && (
          <ul role="list" className="divide-y divide-rule rounded-[var(--radius-sheet)] border border-rule bg-sheet">
            {data.map((l) => (
              <li key={l.lesson_id}>
                <Link
                  href={`/teacher/lessons/${l.lesson_id}/review`}
                  className="flex flex-wrap items-center gap-x-6 gap-y-1 px-5 py-4 hover:bg-paper"
                >
                  <span className="min-w-0 flex-1">
                    <SubjectName subject={l.subject} />
                    <span className="block font-serif text-lg leading-snug font-semibold text-ink">{l.title}</span>
                  </span>
                  <span className="text-sm font-semibold text-ink">{l.class_label}</span>
                  {l.closed_at && (
                    <span className="figures text-sm text-pencil">
                      {new Date(l.closed_at).toLocaleDateString()} {clockTime(l.closed_at)}
                    </span>
                  )}
                  {l.scores_to_confirm > 0 && (
                    <span className="text-sm font-bold text-amber">{l.scores_to_confirm} to confirm</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
