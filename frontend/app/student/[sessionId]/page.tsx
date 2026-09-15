"use client";

import { use } from "react";
import { api } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { StudentLesson } from "@/components/student-lesson";

export default function StudentWork({ params }: PageProps<"/student/[sessionId]">) {
  const { sessionId } = use(params);
  const me = useSignedIn("student");
  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <StudentLesson sessionId={sessionId} load={() => api.studentSession(sessionId)} />
    </>
  );
}
