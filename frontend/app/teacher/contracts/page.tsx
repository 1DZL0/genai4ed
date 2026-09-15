"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, type ClassOut, type PlanSummary } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Button, ErrorNote, Skeleton, SubjectName } from "@/components/ui";

const LIMIT_WORDS: Record<string, string> = {
  attempt: "no help at all",
  diagnostic_question: "asking a question back",
  conceptual_cue: "a cue",
  targeted_hint: "a hint",
  analogous_example: "a similar example",
  partial_step: "part of a step",
  full_solution: "the full answer",
};

export default function LessonPlans() {
  const router = useRouter();
  const me = useSignedIn("teacher");

  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [classes, setClasses] = useState<ClassOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [using, setUsing] = useState<string | null>(null);
  const [classId, setClassId] = useState("");

  useEffect(() => {
    if (!me) return;
    api
      .plans()
      .then(setPlans)
      .catch((e: ApiError) => setError(e.message));
    api
      .classes()
      .then((rows) => {
        setClasses(rows);
        setClassId((current) => current || (rows[0]?.id ?? ""));
      })
      .catch(() => setError("Could not load your classes."));
  }, [me]);

  async function approve(id: string) {
    setBusy(id);
    try {
      const updated = await api.approvePlan(id);
      setPlans((all) => (all ?? []).map((p) => (p.id === id ? updated : p)));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  const [undo, setUndo] = useState<PlanSummary | null>(null);

  async function duplicate(plan: PlanSummary) {
    setBusy(plan.id);
    setError(null);
    try {
      const copy = await api.duplicatePlan(plan.id);
      router.push(`/teacher/contracts/${copy.id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  async function remove(plan: PlanSummary) {
    const newerDraft = plan.status === "draft" && plan.version > 1;
    const message = newerDraft
      ? `Discard the draft of version ${plan.version}? Version ${plan.approved_version ?? plan.version - 1} stays as it is.`
      : plan.used_with.length > 0
        ? `Delete "${plan.title}"? Past lessons and students' work are kept.`
        : `Delete "${plan.title}"? It hasn't been used with a class, so it is removed for good.`;
    if (!window.confirm(message)) return;
    setBusy(plan.id);
    setError(null);
    try {
      const result = await api.deletePlan(plan.id);
      setPlans(await api.plans());
      setUndo(result.outcome === "archived" ? plan : null);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function restore(plan: PlanSummary) {
    try {
      await api.restorePlan(plan.id);
      setPlans(await api.plans());
      setUndo(null);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function book(plan: PlanSummary, startNow: boolean) {
    const version = plan.approved_version_id;
    if (!version || !classId) return;
    setBusy(plan.id);
    setError(null);
    try {
      const lesson = await api.bookLesson(version, classId, new Date().toISOString());
      setUsing(null);
      if (startNow) {
        await api.startLesson(lesson.lesson_id);
        router.push(`/teacher/${lesson.lesson_id}`);
      } else {
        router.push("/teacher");
      }
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  if (!me) return null;

  const field =
    "h-10 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink hover:border-pencil focus:border-ink focus:outline-none";

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle
          lede="A plan has to be approved before a class can use it. You can use the same plan with any of your classes."
          actions={
            <Link
              href="/teacher/new"
              className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-ink px-4 text-sm font-semibold text-white hover:bg-ink-hover"
            >
              Write a lesson plan
            </Link>
          }
        >
          Lesson plans
        </PageTitle>

        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        {undo && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-rule bg-sunken px-4 py-3 text-sm text-ink">
            <span>
              &ldquo;{undo.title}&rdquo; deleted. Its past lessons are kept.
            </span>
            <Button size="sm" variant="quiet" onClick={() => restore(undo)}>
              Undo
            </Button>
          </div>
        )}
        {!error && plans === null && <Skeleton label="Loading your lesson plans" rows={3} />}
        {plans?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5 py-8">
            <p className="font-semibold text-ink">You haven&apos;t written a lesson plan yet.</p>
            <Link href="/teacher/new" className="mt-2 inline-block text-sm font-semibold text-ink underline underline-offset-4">
              Write your first lesson plan
            </Link>
          </div>
        )}

        {plans && plans.length > 0 && (
          <ul role="list" className="space-y-3">
            {plans.map((p) => {
              const draft = p.status === "draft";
              const open = using === p.id;
              return (
                <li key={p.id} className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-3">
                        <SubjectName subject={p.subject} />
                        <span className={`text-xs font-bold ${draft ? "text-amber" : "text-tick"}`}>
                          {draft
                            ? p.approved_version
                              ? `Version ${p.version} draft, classes use version ${p.approved_version}`
                              : "Draft, not approved"
                            : `Approved, version ${p.version}`}
                        </span>
                      </div>
                      <p className="mt-1 font-serif text-lg font-semibold text-ink">{p.title}</p>
                      <p className="mt-1 text-sm text-pencil">
                        {p.items} task{p.items === 1 ? "" : "s"}, {p.minutes} minutes. The tutor can go as far as{" "}
                        {LIMIT_WORDS[p.max_rung] ?? p.max_rung}
                        {p.allow_full_solution && p.max_rung !== "full_solution" ? ", and may give the full answer" : ""}.
                      </p>
                      {p.used_with.length > 0 && (
                        <p className="mt-1 text-xs text-faint">Used with {p.used_with.join(", ")}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {draft && (
                        <Button variant="quiet" onClick={() => approve(p.id)} disabled={busy === p.id}>
                          {busy === p.id ? "Approving…" : "Approve"}
                        </Button>
                      )}
                      {p.approved_version_id && (
                        <Button
                          variant={open ? "quiet" : "primary"}
                          onClick={() => setUsing(open ? null : p.id)}
                          aria-expanded={open}
                        >
                          {open ? "Cancel" : "Use with a class"}
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
                    <Link href={`/teacher/contracts/${p.id}`} className="text-sm text-pencil underline underline-offset-4 hover:text-ink">
                      {draft ? "Edit" : "Edit as a new version"}
                    </Link>
                    <Button variant="plain" onClick={() => duplicate(p)} disabled={busy === p.id}>
                      Duplicate
                    </Button>
                    <Button variant="plain" onClick={() => remove(p)} disabled={busy === p.id}>
                      {draft && p.version > 1 ? "Discard draft" : "Delete"}
                    </Button>
                  </div>

                  {open && (
                    <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-rule pt-4">
                      <div>
                        <label htmlFor={`class-${p.id}`} className="mb-1 block text-sm font-medium text-ink">
                          Class
                        </label>
                        <select
                          id={`class-${p.id}`}
                          value={classId}
                          onChange={(e) => setClassId(e.target.value)}
                          className={field}
                        >
                          {classes.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.label} ({c.students} students)
                            </option>
                          ))}
                        </select>
                      </div>
                      <Button onClick={() => book(p, true)} disabled={busy === p.id || !classId}>
                        {busy === p.id ? "Starting…" : "Start now"}
                      </Button>
                      <Button variant="quiet" onClick={() => book(p, false)} disabled={busy === p.id || !classId}>
                        Book for today
                      </Button>
                    </div>
                  )}
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
