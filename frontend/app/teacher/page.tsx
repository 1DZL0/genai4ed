"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { agentApi, ApiError, type DesignCard } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat } from "@/components/agent-chat";
import { clockTime, ErrorNote, Skeleton, SubjectName } from "@/components/ui";

const STARTERS = [
  "I want to teach this class about photosynthesis. They covered basic cell biology last week. Make it a 30-minute interactive activity.",
  "Year 9 English: practise writing an argumentative paragraph. Hints are fine, but the agent must never write it for them.",
  "A 20-minute check on solving linear equations with the unknown on both sides.",
];

export default function TeacherHome() {
  const router = useRouter();
  const me = useSignedIn("teacher");
  const { data: lessons, error } = useSWR<DesignCard[]>(me ? "designs" : null, agentApi.designs, {
    refreshInterval: 15000,
  });
  const [pending, setPending] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  if (!me) return null;

  async function start(text: string, files: File[]) {
    setStartError(null);
    setPending(text || `Attached ${files.map((f) => f.name).join(", ")}`);
    try {
      if (files.length === 0) {
        const design = await agentApi.startDesign(text);
        router.push(`/teacher/studio/${design.id}`);
        return;
      }
      const design = await agentApi.startDesign("");
      const ids: string[] = [];
      for (const file of files) ids.push((await agentApi.uploadMaterial(design.id, file)).id);
      await agentApi.talk(
        design.id,
        text || "Build a lesson from the material I've attached.",
        ids,
      );
      router.push(`/teacher/studio/${design.id}`);
    } catch (e) {
      setStartError((e as ApiError).message);
      setPending(null);
    }
  }

  const live = lessons?.filter((l) => l.live) ?? [];
  const rest = lessons?.filter((l) => !l.live) ?? [];

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6">
        <section aria-labelledby="new-lesson" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet p-5 sm:p-6">
          <h1 id="new-lesson" className="font-serif text-2xl font-semibold text-ink">
            What do you want to teach?
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-pencil">
            Describe it the way you&apos;d tell a colleague: the topic, the class, what they already
            know, how long, and how the agent should behave. Attach slides, notes or a worksheet if
            you have them. The class agent drafts the lesson with you, then teaches each student.
          </p>
          <div className="mt-4">
            <AgentChat
              lines={pending ? [{ id: "p", who: "me", text: pending }] : []}
              pending={pending !== null}
              pendingText="Drafting your lesson…"
              onSend={start}
              onFiles
              placeholder="e.g. Teach 8C about the causes of the First World War…"
              chips={pending ? [] : STARTERS.map((s) => ({ label: s.split(".")[0], fill: s }))}
              error={startError}
            />
          </div>
        </section>

        {error && (
          <div className="mt-6">
            <ErrorNote>{(error as ApiError).message}</ErrorNote>
          </div>
        )}
        {!lessons && !error && (
          <div className="mt-8">
            <Skeleton label="Loading your lessons" rows={3} />
          </div>
        )}

        {live.length > 0 && (
          <section aria-labelledby="live" className="mt-10">
            <h2 id="live" className="mb-3 text-base font-bold text-ink">
              Running now
            </h2>
            <ul role="list" className="grid gap-3 md:grid-cols-2">
              {live.map((l) => (
                <li key={l.plan_id}>
                  <Link
                    href={`/teacher/live/${l.live!.lesson_id}`}
                    className={`flex h-full flex-col gap-1 rounded-[var(--radius-sheet)] border bg-sheet px-5 py-4 hover:border-ink ${
                      l.live!.open_alerts ? "border-red-pen/60" : "border-rule"
                    }`}
                  >
                    <SubjectName subject={l.subject} />
                    <span className="font-serif text-lg font-semibold text-ink">{l.title}</span>
                    <span className="flex flex-wrap gap-x-4 text-sm">
                      <span className="font-semibold text-ink">{l.live!.class_label}</span>
                      {l.live!.status === "paused" && <span className="font-semibold text-amber">Paused</span>}
                      {l.live!.open_alerts > 0 && (
                        <span className="font-bold text-red-pen">
                          {l.live!.open_alerts} {l.live!.open_alerts === 1 ? "needs" : "need"} you
                        </span>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {lessons && (
          <section aria-labelledby="yours" className="mt-10">
            <h2 id="yours" className="mb-3 text-base font-bold text-ink">
              Your lessons
            </h2>
            {rest.length === 0 && live.length === 0 ? (
              <p className="text-sm text-pencil">No lessons yet. Describe one above to start.</p>
            ) : (
              <ul role="list" className="divide-y divide-rule rounded-[var(--radius-sheet)] border border-rule bg-sheet">
                {rest.map((l) => (
                  <li key={l.plan_id} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4">
                    <Link href={`/teacher/studio/${l.id}`} className="min-w-0 flex-1 group">
                      <SubjectName subject={l.subject} />
                      <span className="block font-serif text-lg leading-snug font-semibold text-ink group-hover:underline">
                        {l.title}
                      </span>
                      <span className="text-sm text-pencil">
                        {l.steps > 0 ? `${l.steps} steps, ${l.duration_minutes} min` : "Not drafted yet"}
                      </span>
                    </Link>
                    <span className={`text-sm font-semibold ${l.status === "draft" ? "text-amber" : "text-tick"}`}>
                      {l.status === "draft"
                        ? l.approved_version_id
                          ? "Changes not approved"
                          : "Draft"
                        : "Ready to teach"}
                    </span>
                    {l.last_run && (
                      <Link
                        href={`/teacher/live/${l.last_run.lesson_id}/review`}
                        className="text-sm text-pencil underline underline-offset-4 hover:text-ink"
                      >
                        Review {l.last_run.class_label}
                        {l.last_run.closed_at ? ` (${clockTime(l.last_run.closed_at)})` : ""}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </main>
    </>
  );
}
