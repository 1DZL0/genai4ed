"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, type ContractOut } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import { Button, DevBanner, Empty, ErrorNote, Panel, Skeleton } from "@/components/ui";

const RUNG_LABEL: Record<string, string> = {
  attempt: "no help",
  diagnostic_question: "a diagnostic question",
  conceptual_cue: "a conceptual cue",
  targeted_hint: "a targeted hint",
  analogous_example: "an analogous example",
  partial_step: "a partial step",
  full_solution: "the full solution",
};

export default function Contracts() {
  const router = useRouter();
  const who = useIdentity();

  const [contracts, setContracts] = useState<ContractOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!who) return;
    api
      .contracts(who)
      .then(setContracts)
      .catch((e: ApiError) => setError(e.message));
  }, [who]);

  async function activate(id: string) {
    if (!who) return;
    setBusy(id);
    try {
      const updated = await api.activateContract(who, id);
      setContracts((all) => (all ?? []).map((c) => (c.id === id ? updated : c)));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function open(id: string) {
    if (!who) return;
    setBusy(id);
    try {
      const { session_id } = await api.openSession(who, id, 50);
      router.push(`/teacher/${session_id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  if (who === undefined) return null;
  if (who === null) return <NotIdentified />;

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-3xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between gap-3">
          <h1 className="text-xl font-semibold text-ink">Your lessons</h1>
          <Link
            href="/teacher/new"
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Write a lesson
          </Link>
        </div>

        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        <Panel title="Lessons">
          {!error && contracts === null && <Skeleton label="Loading your lessons" rows={2} />}
          {contracts?.length === 0 && (
            <Empty>You have not written a lesson yet.</Empty>
          )}
          {contracts && contracts.length > 0 && (
            <ul role="list" className="divide-y divide-border-subtle">
              {contracts.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink">{c.title}</p>
                    <p className="text-xs text-muted">
                      {c.items} question{c.items === 1 ? "" : "s"} · help stops at{" "}
                      {RUNG_LABEL[c.max_rung] ?? c.max_rung}
                      {c.allow_full_solution ? " · full answer permitted" : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[11px] ${
                        c.status === "active"
                          ? "border-accent/30 bg-accent-soft text-accent"
                          : "border-border-strong text-muted"
                      }`}
                    >
                      {c.status}
                    </span>
                    {c.status === "draft" ? (
                      <Button onClick={() => activate(c.id)} disabled={busy === c.id}>
                        {busy === c.id ? "Activating…" : "Activate"}
                      </Button>
                    ) : (
                      <Button variant="quiet" onClick={() => open(c.id)} disabled={busy === c.id}>
                        {busy === c.id ? "Opening…" : "Open a session"}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <p className="mt-4 text-xs text-faint">
          Activating records that you approved these limits, against your name and the time. A
          session admits the whole class and runs for 50 minutes.
        </p>
      </main>
    </>
  );
}
