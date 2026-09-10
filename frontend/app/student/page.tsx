"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type SessionSummary } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import { DevBanner, Empty, ErrorNote, Panel, Skeleton } from "@/components/ui";

export default function StudentSessions() {
  const router = useRouter();
  const who = useIdentity();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!who) return;
    api
      .mySessions(who)
      .then(setSessions)
      .catch((e: ApiError) => setError(e.message));
  }, [who]);

  if (who === undefined) return null; // still hydrating
  if (who === null) return <NotIdentified />;

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-2xl px-4 py-8">
        <h1 className="mb-6 text-xl font-semibold text-ink">Your lessons</h1>
        <Panel title="Open now">
          {error && <ErrorNote>{error}</ErrorNote>}
          {!error && sessions === null && <Skeleton label="Loading your lessons" rows={2} />}
          {sessions?.length === 0 && <Empty>No lesson is open for you at the moment.</Empty>}
          {sessions && sessions.length > 0 && (
            <ul role="list" className="divide-y divide-border-subtle">
              {sessions.map((s) => (
                <li key={s.session_id}>
                  <a
                    href={`/student/${s.session_id}`}
                    className="flex items-center justify-between gap-4 py-3 hover:bg-sunken"
                  >
                    <span>
                      <span className="block text-sm font-medium text-ink">{s.title}</span>
                      <span className="block text-xs text-muted">
                        {s.items} questions · closes{" "}
                        {new Date(s.closes_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </span>
                    <span aria-hidden className="text-muted">
                      →
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
