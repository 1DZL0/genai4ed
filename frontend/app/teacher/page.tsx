"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type TeacherSessionSummary } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import { DevBanner, Empty, ErrorNote, Panel, Skeleton } from "@/components/ui";

export default function TeacherSessions() {
  const router = useRouter();
  const who = useIdentity();
  const [sessions, setSessions] = useState<TeacherSessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!who) return;
    api
      .teacherSessions(who)
      .then(setSessions)
      .catch((e: ApiError) => setError(e.message));
  }, [who]);

  if (who === undefined) return null; // still hydrating
  if (who === null) return <NotIdentified />;

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-2xl px-4 py-8">
        <h1 className="mb-6 text-xl font-semibold text-ink">Your classes</h1>
        <Panel title="Sessions">
          {error && <ErrorNote>{error}</ErrorNote>}
          {!error && sessions === null && <Skeleton label="Loading your sessions" rows={2} />}
          {sessions?.length === 0 && <Empty>You have no sessions yet.</Empty>}
          {sessions && sessions.length > 0 && (
            <ul role="list" className="divide-y divide-border-subtle">
              {sessions.map((s) => (
                <li key={s.session_id}>
                  <a
                    href={`/teacher/${s.session_id}`}
                    className="flex items-center justify-between gap-4 py-3 hover:bg-sunken"
                  >
                    <span>
                      <span className="block text-sm font-medium text-ink">
                        {s.class_label} · {s.title}
                      </span>
                      <span className="block text-xs text-muted">{s.status}</span>
                    </span>
                    <span className="text-xs text-muted">
                      {s.open_exceptions > 0
                        ? `${s.open_exceptions} need${s.open_exceptions === 1 ? "s" : ""} you`
                        : "nothing waiting"}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </main>
    </>
  );
}
