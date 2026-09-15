"use client";

import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { PlanEditor } from "@/components/plan-editor";

export default function NewPlan() {
  const me = useSignedIn("teacher");
  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <PageTitle lede="The tutor can only use what you write here, and never goes past the limit you set. It doesn't make up questions, hints or diagnoses.">
          Write a lesson plan
        </PageTitle>
        <PlanEditor />
      </main>
    </>
  );
}
