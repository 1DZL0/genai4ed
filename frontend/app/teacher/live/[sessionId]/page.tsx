"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { agentApi, api, ApiError, type Live, type StudentDetail, type StudentState } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat, type ChatLine } from "@/components/agent-chat";
import { OPEN_STUDENT_EVENT } from "@/components/walkthrough-bar";
import {
  Button,
  clockTime,
  ErrorNote,
  Notice,
  QueueKind,
  Skeleton,
  SubjectName,
  Tick,
  TimeLeft,
} from "@/components/ui";

const POLL_MS = 5000;

const GROUPS: { state: StudentState["state"]; label: string; tone: string }[] = [
  { state: "needs_you", label: "Needs you", tone: "text-red-pen" },
  { state: "struggling", label: "Struggling", tone: "text-amber" },
  { state: "working", label: "Working", tone: "text-ink" },
  { state: "finished", label: "Finished", tone: "text-tick" },
  { state: "not_started", label: "Not started", tone: "text-pencil" },
];

const CLASS_CHIPS = [
  { label: "Who's struggling?", send: "Who is struggling right now, and with what?" },
  { label: "Common misconceptions?", send: "What misconceptions are showing up across the class?" },
  { label: "What should I do next?", send: "What would be the most useful thing for me to do next?" },
];

export default function LiveLesson({ params }: PageProps<"/teacher/live/[sessionId]">) {
  const { sessionId } = use(params);
  const router = useRouter();
  const me = useSignedIn("teacher");
  const { data, error, mutate } = useSWR<Live>(
    me ? ["live", sessionId] : null,
    () => agentApi.live(sessionId),
    { refreshInterval: POLL_MS, keepPreviousData: true },
  );
  const [open, setOpen] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [summarising, setSummarising] = useState(false);

  // The walkthrough can point at a student.
  useEffect(() => {
    const onOpen = (e: Event) => setOpen((e as CustomEvent<string>).detail);
    window.addEventListener(OPEN_STUDENT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_STUDENT_EVENT, onOpen);
  }, []);

  if (!me) return null;

  async function ask(text: string) {
    setAsking(text);
    setChatError(null);
    try {
      await mutate(await agentApi.askClass(sessionId, text), { revalidate: false });
    } catch (e) {
      setChatError((e as ApiError).message);
    } finally {
      setAsking(null);
    }
  }

  async function summarise() {
    setSummarising(true);
    setActionError(null);
    try {
      await mutate(await agentApi.refreshInsight(sessionId), { revalidate: false });
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setSummarising(false);
    }
  }

  async function setState(to: "open" | "paused" | "closed") {
    if (to === "closed" && !window.confirm("End the lesson for the whole class? Students can't talk to the agent after this.")) {
      return;
    }
    setActionError(null);
    try {
      await api.setSessionState(sessionId, to);
      if (to === "closed") router.push(`/teacher/live/${sessionId}/review`);
      else await mutate();
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  async function dealtWith(alertId: string) {
    try {
      await api.acknowledge(alertId);
      await mutate();
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  const lines: ChatLine[] = (data?.conversation ?? []).map((m) => ({
    id: m.id,
    who: m.role === "teacher" ? "me" : "agent",
    text: m.text,
  }));
  if (asking) lines.push({ id: "asking", who: "me", text: asking });

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        {error && !data && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!data && !error && <Skeleton label="Loading the lesson" rows={5} />}

        {data && (
          <>
            <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
              <div>
                <SubjectName subject={data.subject} />
                <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{data.title}</h1>
                <p className="mt-1 flex flex-wrap gap-x-4 text-sm">
                  <span className="font-semibold text-ink">{data.class_label}</span>
                  <span className="text-pencil">{data.students.length} students</span>
                  {data.status === "paused" ? (
                    <span className="font-semibold text-amber">Paused</span>
                  ) : (
                    <TimeLeft closesAt={data.closes_at} status={data.status} />
                  )}
                  <Link href={`/teacher/studio/${data.design_id}`} className="text-pencil underline underline-offset-4 hover:text-ink">
                    Lesson brief
                  </Link>
                </p>
              </div>
              <div className="flex gap-2">
                {data.status === "open" && (
                  <Button variant="quiet" onClick={() => setState("paused")}>Pause the class</Button>
                )}
                {data.status === "paused" && <Button onClick={() => setState("open")}>Resume</Button>}
                {data.status !== "closed" ? (
                  <Button variant="quiet" onClick={() => setState("closed")}>End lesson</Button>
                ) : (
                  <Link
                    href={`/teacher/live/${sessionId}/review`}
                    className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-ink px-4 text-sm font-semibold text-white hover:bg-ink-hover"
                  >
                    Review the lesson
                  </Link>
                )}
              </div>
            </header>

            {actionError && (
              <div className="mb-4">
                <ErrorNote>{actionError}</ErrorNote>
              </div>
            )}
            {data.status === "paused" && (
              <div className="mb-4">
                <Notice tone="amber">The class is paused. Students can read back but the agent won&apos;t answer until you resume.</Notice>
              </div>
            )}

            <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <div className="space-y-6">
                <section
                  aria-labelledby="needs-you"
                  className={`rounded-[var(--radius-sheet)] border bg-sheet ${data.alerts.length ? "border-red-pen/50" : "border-rule"}`}
                >
                  <header className="flex items-baseline justify-between px-5 pt-4 pb-3">
                    <h2 id="needs-you" className="text-base font-bold text-ink">Needs you</h2>
                    <span className={`figures text-sm font-bold ${data.alerts.length ? "text-red-pen" : "text-pencil"}`}>
                      {data.alerts.length || "Nobody"}
                    </span>
                  </header>
                  {data.alerts.length === 0 ? (
                    <p className="flex items-center gap-2 px-5 pb-4 text-sm text-pencil">
                      <Tick className="size-4" /> Nothing needs you. The agent keeps routine things in the record.
                    </p>
                  ) : (
                    <ul role="list" className="border-t border-rule">
                      {data.alerts.map((a) => (
                        <li key={a.id} className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-rule px-5 py-3 last:border-b-0">
                          <div className="min-w-0 flex-1">
                            <p className="flex flex-wrap items-baseline gap-x-3">
                              <span className="figures font-bold text-ink">{a.pseudonym}</span>
                              <QueueKind kind={a.kind} priority={a.priority} />
                              <span className="figures text-xs text-faint">{clockTime(a.created_at)}</span>
                            </p>
                            <p className="mt-0.5 text-sm text-ink">{a.summary}</p>
                          </div>
                          <div className="flex gap-2">
                            <Button size="sm" variant="quiet" onClick={() => setOpen(a.student_id)}>Look</Button>
                            <Button variant="plain" onClick={() => dealtWith(a.id)}>Dealt with</Button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-labelledby="class" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                  <h2 id="class" className="mb-3 text-base font-bold text-ink">The class</h2>
                  <div className="space-y-4">
                    {GROUPS.map((g) => {
                      const members = data.students.filter((s) => s.state === g.state);
                      if (members.length === 0) return null;
                      return (
                        <div key={g.state}>
                          <p className={`mb-1.5 text-sm font-semibold ${g.tone}`}>
                            {g.label} <span className="figures font-normal text-pencil">({members.length})</span>
                          </p>
                          <ul role="list" className="flex flex-wrap gap-2">
                            {members.map((s) => (
                              <li key={s.student_id}>
                                <button
                                  onClick={() => setOpen(s.student_id)}
                                  title={s.note || undefined}
                                  className={`flex flex-col items-start rounded-[var(--radius-control)] border px-3 py-1.5 text-left hover:border-ink ${
                                    open === s.student_id ? "border-ink bg-sunken" : "border-rule bg-sheet"
                                  }`}
                                >
                                  <span className="figures text-sm font-bold text-ink">{s.pseudonym}</span>
                                  <span className="max-w-44 truncate text-xs text-pencil">
                                    {s.state === "finished" ? "Done" : s.state === "not_started" ? "Not yet" : s.step_name}
                                  </span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </section>

                {(data.patterns.length > 0 || data.notable.length > 0) && (
                  <section aria-labelledby="patterns" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                    <h2 id="patterns" className="mb-2 text-base font-bold text-ink">Across the class</h2>
                    <ul role="list" className="space-y-2 text-sm">
                      {data.patterns.map((p) => (
                        <li key={p.note}>
                          <span className="font-semibold text-ink">Misconception:</span> {p.note}{" "}
                          <span className="text-pencil">({p.students.join(", ")})</span>
                        </li>
                      ))}
                      {data.notable.slice(-6).map((n, i) => (
                        <li key={`${n.at}-${i}`} className="text-pencil">
                          <span className="figures font-semibold text-ink">{n.pseudonym}</span>: {n.note || n.kind.replace(/_/g, " ")}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>

              <aside className="space-y-6 lg:sticky lg:top-4">
                <section aria-labelledby="summary" className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                  <div className="mb-2 flex items-baseline justify-between gap-3">
                    <h2 id="summary" className="text-base font-bold text-ink">Agent&apos;s summary</h2>
                    <Button variant="plain" onClick={summarise} disabled={summarising}>
                      {summarising ? "Summarising…" : data.insight ? "Refresh" : "Summarise now"}
                    </Button>
                  </div>
                  {data.insight ? (
                    <>
                      <p className="text-sm text-ink">{data.insight.summary}</p>
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink">
                        {data.insight.items.map((item, i) => (
                          <li key={i}>{item.text}</li>
                        ))}
                      </ul>
                      <p className="mt-2 text-xs text-faint">As of {clockTime(data.insight.created_at)}</p>
                    </>
                  ) : (
                    <p className="text-sm text-pencil">Ask for a summary when you want one.</p>
                  )}
                </section>

                <section
                  aria-labelledby="ask"
                  className="flex h-[26rem] flex-col rounded-[var(--radius-sheet)] border border-rule bg-paper p-4"
                >
                  <h2 id="ask" className="mb-1 text-base font-bold text-ink">Ask about the class</h2>
                  <AgentChat
                    className="min-h-0 flex-1"
                    lines={lines}
                    pending={asking !== null}
                    onSend={(text) => ask(text)}
                    chips={CLASS_CHIPS}
                    placeholder="e.g. Who hasn't understood step 2?"
                    error={chatError}
                  />
                </section>
              </aside>
            </div>
          </>
        )}
      </main>

      {open && data && (
        <StudentDrawer
          key={open}
          lessonId={sessionId}
          studentId={open}
          canGuide={data.status !== "closed"}
          onClose={() => setOpen(null)}
        />
      )}
    </>
  );
}

const JUDGMENT: Record<string, string> = {
  met: "Met",
  partial: "Partly",
  not_met: "Not yet",
  unclear: "Unclear",
};

function StudentDrawer({
  lessonId,
  studentId,
  canGuide,
  onClose,
}: {
  lessonId: string;
  studentId: string;
  canGuide: boolean;
  onClose: () => void;
}) {
  const [withConversation, setWithConversation] = useState(false);
  const { data, error, mutate } = useSWR<StudentDetail>(
    ["student", lessonId, studentId, withConversation],
    () => agentApi.studentDetail(lessonId, studentId, withConversation),
  );
  const [text, setText] = useState("");
  const [show, setShow] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [guideError, setGuideError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  useEffect(() => {
    headingRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setSending(true);
    setGuideError(null);
    try {
      await mutate(await agentApi.guide(lessonId, studentId, text.trim(), show), { revalidate: false });
      setText("");
      setSent(true);
    } catch (e) {
      setGuideError((e as ApiError).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className="fixed inset-x-0 bottom-0 top-[var(--walkthrough-h,0px)] z-30 bg-ink/20 lg:hidden"
      />
      <aside
        role="dialog"
        aria-labelledby="drawer-title"
        className="slide-in fixed top-[var(--walkthrough-h,0px)] bottom-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-rule bg-sheet shadow-[-24px_0_48px_-32px_rgba(31,42,68,0.45)]"
      >
        <header className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
          <div>
            <h2 id="drawer-title" ref={headingRef} tabIndex={-1} className="figures text-lg font-bold text-ink focus:outline-none">
              {data?.pseudonym ?? "Student"}
            </h2>
            <p className="text-xs text-pencil">Opening a student is recorded. Students are told their teacher can see their work.</p>
          </div>
          <Button variant="plain" onClick={onClose}>Close</Button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-sm">
          {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
          {!data && !error && <Skeleton label="Loading" rows={3} />}
          {data && (
            <>
              <ul className="space-y-1 text-ink">
                {data.summary.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>

              <div>
                <h3 className="mb-1.5 font-bold text-ink">Steps</h3>
                <ol className="space-y-1">
                  {data.steps.map((s, i) => (
                    <li key={`${s.name}-${i}`} className="flex items-baseline justify-between gap-3">
                      <span className={s.current ? "font-semibold text-ink" : "text-ink"}>
                        {i + 1}. {s.name}
                        {s.current && <span className="ml-1 text-xs text-pencil">(now)</span>}
                      </span>
                      <span className={`text-xs ${s.judgment === "met" ? "text-tick" : s.judgment ? "text-amber" : "text-faint"}`}>
                        {s.judgment ? JUDGMENT[s.judgment] : "–"}
                        {s.attempts > 0 && <span className="figures text-faint"> · {s.attempts} tries</span>}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>

              <div>
                <h3 className="mb-1.5 font-bold text-ink">What the agent recorded</h3>
                {data.evidence.length === 0 ? (
                  <p className="text-pencil">Nothing yet.</p>
                ) : (
                  <ol className="space-y-2">
                    {data.evidence.map((e, i) => (
                      <li key={`${e.at}-${i}`} className="flex gap-3">
                        <span className="figures w-11 shrink-0 text-xs text-faint">{clockTime(e.at)}</span>
                        <span className="min-w-0">
                          <span className="block text-ink">{e.text}</span>
                          {e.detail && <span className="block text-pencil">{e.detail}</span>}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              <div>
                {data.conversation === null ? (
                  <Button size="sm" variant="quiet" onClick={() => setWithConversation(true)}>
                    Read the conversation
                  </Button>
                ) : (
                  <>
                    <h3 className="mb-1.5 font-bold text-ink">Conversation</h3>
                    <ol className="space-y-2">
                      {data.conversation.map((line, i) => (
                        <li
                          key={`${line.at}-${i}`}
                          className={
                            line.who === "student"
                              ? "rounded-[var(--radius-control)] bg-sunken px-3 py-2 text-ink"
                              : line.who === "agent"
                                ? "rounded-[var(--radius-control)] border border-rule px-3 py-2 text-ink"
                                : "px-1 text-xs text-pencil"
                          }
                        >
                          <span className="block text-xs font-semibold text-pencil">
                            {line.who === "student" ? data.pseudonym : line.who === "agent" ? "Class agent" : line.who === "teacher_only" ? "Only you see this" : ""}
                          </span>
                          {line.text}
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </div>
            </>
          )}
        </div>

        {canGuide && (
          <form onSubmit={send} className="border-t border-rule px-5 py-4">
            <label htmlFor="guide" className="text-sm font-bold text-ink">
              Guide the agent for {data?.pseudonym ?? "this student"}
            </label>
            <textarea
              id="guide"
              rows={2}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setSent(false);
              }}
              placeholder="e.g. Use a simpler example, then check they can explain it back."
              className="mt-1.5 block w-full resize-none rounded-[var(--radius-control)] border border-rule-strong px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-ink focus:outline-none"
            />
            <label className="mt-2 flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
              Also show it to the student as a note from me
            </label>
            {guideError && (
              <div className="mt-2">
                <ErrorNote>{guideError}</ErrorNote>
              </div>
            )}
            <div className="mt-2 flex items-center justify-between gap-3">
              <span aria-live="polite" className="text-xs text-tick">{sent ? "The agent will use this next time they reply." : ""}</span>
              <Button type="submit" size="sm" disabled={sending || !text.trim()}>
                {sending ? "Sending…" : "Send"}
              </Button>
            </div>
          </form>
        )}
      </aside>
    </>
  );
}
