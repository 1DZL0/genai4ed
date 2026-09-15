"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, type ContractOut } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Button, ErrorNote, Skeleton, SubjectName } from "@/components/ui";

const LESSON_MINUTES = 50;

const LIMIT_WORDS: Record<string, string> = {
  attempt: "no help at all",
  diagnostic_question: "asking a question back",
  conceptual_cue: "a cue",
  targeted_hint: "a hint",
  analogous_example: "a similar example",
  partial_step: "part of a step",
  full_solution: "the full answer",
};

export default function Lessons() {
  const router = useRouter();
  const me = useSignedIn("teacher");

  const [contracts, setContracts] = useState<ContractOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    api
      .contracts()
      .then(setContracts)
      .catch((e: ApiError) => setError(e.message));
  }, [me]);

  async function approve(id: string) {
    setBusy(id);
    try {
      const updated = await api.activateContract(id);
      setContracts((all) => (all ?? []).map((c) => (c.id === id ? updated : c)));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function start(id: string) {
    setBusy(id);
    try {
      const { session_id } = await api.openSession(id, LESSON_MINUTES);
      router.push(`/teacher/${session_id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle
          lede={`A lesson has to be approved before it can run. Starting one lets the whole class in for ${LESSON_MINUTES} minutes.`}
          actions={
            <Link
              href="/teacher/new"
              className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-ink px-4 text-sm font-semibold text-white hover:bg-ink-hover"
            >
              Write a lesson
            </Link>
          }
        >
          Lessons
        </PageTitle>

        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        {!error && contracts === null && <Skeleton label="Loading your lessons" rows={3} />}
        {contracts?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5 py-8">
            <p className="font-semibold text-ink">You haven&apos;t written a lesson yet.</p>
            <Link href="/teacher/new" className="mt-2 inline-block text-sm font-semibold text-ink underline underline-offset-4">
              Write your first lesson
            </Link>
          </div>
        )}

        {contracts && contracts.length > 0 && (
          <ul role="list" className="space-y-3">
            {contracts.map((c) => {
              const draft = c.status === "draft";
              return (
                <li
                  key={c.id}
                  className="flex flex-wrap items-center gap-4 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-3">
                      <SubjectName subject={c.subject} />
                      <span
                        className={`text-xs font-bold ${draft ? "text-amber" : "text-tick"}`}
                      >
                        {draft ? "Draft, not approved" : c.status === "active" ? "Approved" : "Closed"}
                      </span>
                    </div>
                    <p className="mt-1 font-serif text-lg font-semibold text-ink">{c.title}</p>
                    <p className="mt-1 text-sm text-pencil">
                      {c.items} question{c.items === 1 ? "" : "s"}. The tutor can go as far as{" "}
                      {LIMIT_WORDS[c.max_rung] ?? c.max_rung}
                      {c.allow_full_solution && c.max_rung !== "full_solution" ? ", and may give the full answer" : ""}.
                    </p>
                  </div>
                  <div className="flex items-center">
                    {draft ? (
                      <Button variant="quiet" onClick={() => approve(c.id)} disabled={busy === c.id}>
                        {busy === c.id ? "Approving…" : "Approve"}
                      </Button>
                    ) : c.status === "active" ? (
                      <Button onClick={() => start(c.id)} disabled={busy === c.id}>
                        {busy === c.id ? "Starting…" : "Start lesson"}
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <p className="mt-6 text-sm text-pencil">
          Approving records that you agreed to these limits, with your name and the time.
        </p>
      </main>
    </>
  );
}
