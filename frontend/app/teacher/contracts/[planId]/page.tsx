"use client";

import { use } from "react";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { PlanEditor } from "@/components/plan-editor";

export default function EditPlan({ params }: PageProps<"/teacher/contracts/[planId]">) {
  const { planId } = use(params);
  const me = useSignedIn("teacher");
  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <PageTitle lede="Changes stay in a draft until you approve them. Lessons already taught keep the version they used.">
          Edit lesson plan
        </PageTitle>
        <PlanEditor key={planId} planId={planId} />
      </main>
    </>
  );
}
