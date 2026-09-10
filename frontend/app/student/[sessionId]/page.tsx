"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type AttemptResult, type Item, type StudentSession } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import { Button, DevBanner, ErrorNote, Skeleton } from "@/components/ui";

type Turn = { mine: string; correct: boolean; tutor: string; helped: boolean };

export default function StudentWork({ params }: PageProps<"/student/[sessionId]">) {
  const { sessionId } = use(params);
  const router = useRouter();

  const who = useIdentity();
  const [session, setSession] = useState<StudentSession | null>(null);
  const [active, setActive] = useState<Item | null>(null);
  const [turns, setTurns] = useState<Record<string, Turn[]>>({});
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!who) return;
    api
      .studentSession(who, sessionId)
      .then((s) => {
        setSession(s);
        setActive(s.items[0] ?? null);
      })
      .catch((e: ApiError) => setError(e.message));
  }, [sessionId, who]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, active]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!who || !active || !answer.trim() || busy) return;

    setBusy(true);
    setError(null);
    const mine = answer;
    try {
      const result: AttemptResult = await api.submitAttempt(who, sessionId, active.id, mine);
      setTurns((t) => ({
        ...t,
        [active.id]: [
          ...(t[active.id] ?? []),
          {
            mine,
            correct: result.correct,
            tutor: result.tutor_message,
            helped: result.help_given,
          },
        ],
      }));
      setAnswer("");
    } catch (e) {
      const err = e as ApiError;
      setError(
        err.status === 409
          ? "Your teacher has paused this activity."
          : `Could not send that: ${err.message}`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function askForTeacher() {
    if (!who) return;
    try {
      await api.requestTeacher(who, sessionId);
      setAsked(true);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  if (who === undefined) return null; // still hydrating
  if (who === null) return <NotIdentified />;

  const thread = active ? (turns[active.id] ?? []) : [];

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        {error && !session && <ErrorNote>{error}</ErrorNote>}
        {!session && !error && <Skeleton label="Loading your lesson" rows={4} />}

        {session && (
          <>
            <header className="mb-5">
              <h1 className="text-xl font-semibold text-ink">{session.title}</h1>
              {session.material_notes && (
                <p className="mt-1 text-sm text-muted">{session.material_notes}</p>
              )}
              {session.status === "paused" && (
                <p role="alert" className="mt-3 rounded border border-sev2/30 bg-sev2/5 px-3 py-2 text-sm">
                  Your teacher has paused this activity.
                </p>
              )}
            </header>

            <nav aria-label="Questions" className="mb-5 flex flex-wrap gap-2">
              {session.items.map((item) => {
                const done = (turns[item.id] ?? []).some((t) => t.correct);
                const current = active?.id === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setActive(item)}
                    aria-current={current ? "true" : undefined}
                    className={`rounded border px-3 py-1.5 text-sm transition-colors ${
                      current
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-border-subtle bg-surface text-muted hover:bg-sunken"
                    }`}
                  >
                    {done && <span aria-hidden>✓ </span>}
                    Question {item.ordinal}
                    {done && <span className="sr-only"> (answered correctly)</span>}
                  </button>
                );
              })}
            </nav>

            {active && (
              <section aria-labelledby="prompt" className="rounded border border-border-subtle bg-surface">
                <div className="border-b border-border-subtle px-4 py-4">
                  <h2 id="prompt" className="font-mono text-lg text-ink">
                    {active.prompt}
                  </h2>
                </div>

                <div className="space-y-3 px-4 py-4">
                  {thread.length === 0 && (
                    <p className="text-sm text-muted">
                      Work it out, then type your answer below.
                    </p>
                  )}

                  {thread.map((turn, i) => (
                    <div key={i} className="space-y-2">
                      <p className="flex items-baseline gap-2 text-sm">
                        <span className="text-faint">You answered</span>
                        <span className="font-mono text-ink">{turn.mine}</span>
                        <span className={turn.correct ? "text-correct" : "text-incorrect"}>
                          {turn.correct ? "✓ correct" : "✗ not right"}
                        </span>
                      </p>
                      <p className="rounded bg-sunken px-3 py-2 text-sm text-ink">{turn.tutor}</p>
                    </div>
                  ))}
                  <div ref={endRef} />
                </div>

                <form onSubmit={submit} className="flex gap-2 border-t border-border-subtle px-4 py-3">
                  <label htmlFor="answer" className="sr-only">
                    Your answer to question {active.ordinal}
                  </label>
                  <input
                    id="answer"
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    disabled={busy || session.status !== "open"}
                    autoComplete="off"
                    placeholder="x = …"
                    className="flex-1 rounded border border-border-strong bg-surface px-3 py-2
                               font-mono text-sm text-ink placeholder:text-faint disabled:bg-sunken"
                  />
                  <Button type="submit" disabled={busy || !answer.trim() || session.status !== "open"}>
                    {busy ? "Checking…" : "Submit"}
                  </Button>
                </form>
              </section>
            )}

            {error && session && (
              <div className="mt-3">
                <ErrorNote>{error}</ErrorNote>
              </div>
            )}

            <div className="mt-5 flex items-center justify-between gap-4">
              <p className="text-xs text-muted">{session.disclosure}</p>
              <Button variant="quiet" onClick={askForTeacher} disabled={asked}>
                {asked ? "Your teacher has been told" : "Ask my teacher"}
              </Button>
            </div>
          </>
        )}
      </main>
    </>
  );
}
