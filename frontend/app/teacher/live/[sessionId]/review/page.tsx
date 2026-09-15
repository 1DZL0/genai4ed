"use client";

import { use, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { agentApi, ApiError, type Outcome, type ReviewPage } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { Button, clockTime, ErrorNote, Notice, Skeleton, SubjectName } from "@/components/ui";

export default function LessonReview({ params }: PageProps<"/teacher/live/[sessionId]/review">) {
  const { sessionId } = use(params);
  const me = useSignedIn("teacher");
  const { data, error, mutate } = useSWR<ReviewPage>(me ? ["review", sessionId] : null, () =>
    agentApi.review(sessionId),
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!me) return null;

  async function suggest() {
    setBusy(true);
    setActionError(null);
    try {
      await mutate(await agentApi.suggestOutcomes(sessionId), { revalidate: false });
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const live = data?.live;
  const waiting = data?.outcomes.filter((o) => o.status === "suggested").length ?? 0;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!data && !error && <Skeleton label="Loading the review" rows={4} />}

        {data && live && (
          <>
            <header className="mb-6">
              <Link href={`/teacher/live/${sessionId}`} className="text-sm text-pencil underline underline-offset-4 hover:text-ink">
                Back to the lesson
              </Link>
              <div className="mt-2">
                <SubjectName subject={live.subject} />
              </div>
              <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{live.title}</h1>
              <p className="mt-1 text-sm text-pencil">
                {live.class_label} · {live.students.length} students
                {live.status !== "closed" && " · still running"}
              </p>
            </header>

            {actionError && (
              <div className="mb-4">
                <ErrorNote>{actionError}</ErrorNote>
              </div>
            )}

            <dl className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Finished", live.students.filter((s) => s.state === "finished").length],
                ["Still needed you", live.alerts.length],
                ["Shared misconceptions", live.patterns.length],
                ["Outcomes to confirm", waiting],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3">
                  <dt className="text-xs text-pencil">{label}</dt>
                  <dd className="figures font-serif text-2xl font-semibold text-ink">{value}</dd>
                </div>
              ))}
            </dl>

            <section className="mb-6 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="text-base font-bold text-ink">The agent&apos;s review</h2>
                {live.status === "closed" && data.criteria.length > 0 && data.students_without_outcome.length > 0 && (
                  <Button onClick={suggest} disabled={busy}>
                    {busy ? "Reviewing…" : data.outcomes.length ? "Suggest the rest" : "Review and suggest outcomes"}
                  </Button>
                )}
              </div>
              {live.insight ? (
                <>
                  <p className="mt-2 text-sm text-ink">{live.insight.summary}</p>
                  <p className="mt-1 text-xs text-faint">Written {clockTime(live.insight.created_at)}</p>
                </>
              ) : (
                <p className="mt-2 text-sm text-pencil">
                  {live.status === "closed"
                    ? "Ask the agent to review the lesson. It suggests an outcome for each student from what they showed; you confirm each one."
                    : "End the lesson to review outcomes."}
                </p>
              )}
              {live.patterns.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {live.patterns.map((p) => (
                    <li key={p.note}>
                      <span className="font-semibold text-ink">Misconception:</span> {p.note}{" "}
                      <span className="text-pencil">({p.students.join(", ")})</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {data.criteria.length === 0 && (
              <Notice>This lesson has no assessment criteria, so there are no outcomes to confirm.</Notice>
            )}

            {data.outcomes.length > 0 && (
              <section aria-labelledby="outcomes">
                <h2 id="outcomes" className="mb-3 text-base font-bold text-ink">
                  Outcomes <span className="text-sm font-normal text-pencil">(students see them once you confirm)</span>
                </h2>
                <ul role="list" className="space-y-3">
                  {data.outcomes.map((o) => (
                    <OutcomeRow key={o.id} lessonId={sessionId} outcome={o} onSaved={(page) => mutate(page, { revalidate: false })} />
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}

function OutcomeRow({
  lessonId,
  outcome,
  onSaved,
}: {
  lessonId: string;
  outcome: Outcome;
  onSaved: (page: ReviewPage) => void;
}) {
  const source = outcome.confirmed ?? outcome.suggested;
  const [open, setOpen] = useState(false);
  const [points, setPoints] = useState<Record<string, number>>(
    Object.fromEntries(source.criteria.map((c) => [c.name, c.points])),
  );
  const [comment, setComment] = useState(outcome.comment ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = Object.values(points).reduce((a, b) => a + b, 0);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onSaved(await agentApi.confirmOutcome(lessonId, outcome.id, points, comment));
      setOpen(false);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full flex-wrap items-baseline justify-between gap-3 px-5 py-3 text-left">
        <span className="figures font-bold text-ink">{outcome.pseudonym}</span>
        <span className={`figures text-sm font-semibold ${outcome.status === "confirmed" ? "text-tick" : "text-amber"}`}>
          {outcome.status === "confirmed"
            ? `${outcome.confirmed_total}/${outcome.out_of} confirmed`
            : `${outcome.suggested_total}/${outcome.out_of} suggested`}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-rule px-5 py-4 text-sm">
          <table className="w-full text-left">
            <tbody>
              {outcome.suggested.criteria.map((c) => (
                <tr key={c.name} className="border-b border-rule align-top last:border-b-0">
                  <th scope="row" className="py-2 pr-3 font-semibold text-ink">{c.name}</th>
                  <td className="py-2 pr-3 text-pencil">{c.reason}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <label className="sr-only" htmlFor={`${outcome.id}-${c.name}`}>{c.name} points</label>
                    <input
                      id={`${outcome.id}-${c.name}`}
                      type="number"
                      min={0}
                      max={c.max}
                      value={points[c.name] ?? 0}
                      onChange={(e) =>
                        setPoints((p) => ({ ...p, [c.name]: Math.max(0, Math.min(c.max, Number(e.target.value) || 0)) }))
                      }
                      className="figures h-8 w-14 rounded-[var(--radius-control)] border border-rule-strong px-2 text-right text-ink"
                    />
                    <span className="figures ml-1 text-pencil">/{c.max}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {outcome.suggested.keep && <p className="text-ink"><span className="font-semibold">Went well:</span> {outcome.suggested.keep}</p>}
          {outcome.suggested.develop.length > 0 && (
            <p className="text-ink"><span className="font-semibold">To work on:</span> {outcome.suggested.develop.join(" ")}</p>
          )}
          <div>
            <label htmlFor={`${outcome.id}-comment`} className="font-semibold text-ink">Your comment</label>
            <textarea
              id={`${outcome.id}-comment`}
              rows={2}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="mt-1 block w-full resize-none rounded-[var(--radius-control)] border border-rule-strong px-3 py-2 text-ink"
            />
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="flex items-center justify-between">
            <span className="figures font-semibold text-ink">Total {total}/{outcome.out_of}</span>
            <Button onClick={save} disabled={saving}>
              {saving ? "Saving…" : outcome.status === "confirmed" ? "Update" : "Confirm"}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
