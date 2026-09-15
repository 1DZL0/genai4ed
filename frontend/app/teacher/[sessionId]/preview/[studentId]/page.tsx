"use client";

import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, type CastMember } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { StudentLesson } from "@/components/student-lesson";

export default function StudentPreview({
  params,
}: PageProps<"/teacher/[sessionId]/preview/[studentId]">) {
  const { sessionId, studentId } = use(params);
  const me = useSignedIn("teacher");
  const { data: cast } = useSWR<CastMember[]>(me ? ["cast", sessionId] : null, () =>
    api.walkthroughCast(sessionId),
  );

  if (!me) return null;
  const member = cast?.find((c) => c.student_id === studentId);

  return (
    <>
      <AppHeader me={me} />
      <div className="mx-auto w-full max-w-5xl px-4 pt-6 sm:px-6">
        <nav aria-label="Pretend students" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <Link href={`/teacher/${sessionId}`} className="text-pencil underline underline-offset-4 hover:text-ink">
            Back to the register
          </Link>
          {cast && cast.length > 0 && <span className="text-faint">See another student:</span>}
          {cast?.map((c) => (
            <Link
              key={c.student_id}
              href={`/teacher/${sessionId}/preview/${c.student_id}`}
              title={c.description}
              aria-current={c.student_id === studentId ? "page" : undefined}
              className={`figures rounded-full border px-3 py-1 ${
                c.student_id === studentId
                  ? "border-ink bg-ink text-white"
                  : "border-rule-strong bg-sheet text-ink hover:border-ink"
              }`}
            >
              {c.pseudonym}
            </Link>
          ))}
        </nav>
        {member && <p className="mt-2 text-sm text-pencil">{member.description}</p>}
      </div>
      <StudentLesson
        sessionId={sessionId}
        preview={member?.pseudonym ?? "this student"}
        load={() => api.walkthroughStudentView(sessionId, studentId)}
      />
    </>
  );
}
