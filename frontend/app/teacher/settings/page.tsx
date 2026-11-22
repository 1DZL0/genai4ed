"use client";

import { useSignedIn } from "@/lib/session";
import { PageTitle, Shell } from "@/components/app-header";
import { MemoryPanel, TutorPanel } from "@/components/memory-settings";

/** What a teacher sets once, for every lesson of theirs: whether the tutor adapts to each
 * student, and what it remembers between lessons. */
export default function Settings() {
  const me = useSignedIn("teacher");

  if (!me) return null;

  return (
    <Shell me={me}>
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle lede="These hold for every lesson of yours.">Settings</PageTitle>

        <div className="flex flex-col gap-6">
          {/* A signed-in teacher needs no research key. */}
          <TutorPanel researchKey="" />
          <MemoryPanel researchKey="" />
        </div>
      </main>
    </Shell>
  );
}
