"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { agentApi, api, ApiError, type ClassOut, type Design } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat, type ChatLine } from "@/components/agent-chat";
import { LessonBriefView } from "@/components/lesson-brief";
import { Button, ErrorNote, Notice, Skeleton } from "@/components/ui";

const CHIPS = [
  { label: "Make it shorter", send: "Make it shorter." },
  { label: "More challenging", send: "Make it more challenging for a strong class." },
  { label: "Simpler language", send: "Use simpler language and more examples." },
  { label: "Add a rule…", fill: "Rule for the agent: " },
  { label: "What should be reported to me?", send: "What will you report to me during the lesson, and what should I change?" },
];

export default function Studio({ params }: PageProps<"/teacher/studio/[designId]">) {
  const { designId } = use(params);
  const router = useRouter();
  const me = useSignedIn("teacher");
  const { data: design, error, mutate } = useSWR<Design>(
    me ? ["design", designId] : null,
    () => agentApi.design(designId),
  );
  const { data: classes } = useSWR<ClassOut[]>(me ? "classes" : null, api.classes);

  const [pending, setPending] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"approve" | "run" | null>(null);
  const [classId, setClassId] = useState("");

  if (!me) return null;

  async function send(text: string, files: File[]) {
    if (!design) return;
    setChatError(null);
    const names = files.map((f) => f.name).join(", ");
    setPending(text || `Attached ${names}`);
    try {
      const ids: string[] = [];
      for (const file of files) {
        const uploaded = await agentApi.uploadMaterial(design.id, file);
        ids.push(uploaded.id);
      }
      const message = text || `I've attached ${names}. Use it for this lesson.`;
      const updated = await agentApi.talk(design.id, message, ids);
      if (updated.id !== design.id) {
        router.replace(`/teacher/studio/${updated.id}`);
      }
      await mutate(updated, { revalidate: false });
    } catch (e) {
      setChatError((e as ApiError).message);
      await mutate();
    } finally {
      setPending(null);
    }
  }

  async function approve() {
    if (!design) return;
    setBusy("approve");
    setActionError(null);
    try {
      await mutate(await agentApi.approveDesign(design.id), { revalidate: false });
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function run() {
    const version = design?.status === "active" ? design.id : design?.approved_version_id;
    const target = classId || classes?.[0]?.id;
    if (!version || !target) return;
    setBusy("run");
    setActionError(null);
    try {
      const lesson = await api.bookLesson(version, target, new Date().toISOString());
      await api.startLesson(lesson.lesson_id);
      router.push(`/teacher/live/${lesson.lesson_id}`);
    } catch (e) {
      setActionError((e as ApiError).message);
      setBusy(null);
    }
  }

  const lines: ChatLine[] = (design?.messages ?? []).map((m) => ({
    id: m.id,
    who: m.role === "teacher" ? "me" : "agent",
    text: m.text,
    footnote:
      m.role === "teacher" && m.material_ids.length > 0
        ? `Attached: ${m.material_ids
            .map((id) => design?.materials.find((x) => x.id === id)?.filename ?? "a file")
            .join(", ")}`
        : m.role === "agent" && m.data.brief_changed
          ? "Updated the lesson brief"
          : undefined,
  }));
  if (pending) lines.push({ id: "pending", who: "me", text: pending });

  const runnable = design && (design.status === "active" || design.approved_version_id);
  const live = design?.runs.find((r) => r.status === "open" || r.status === "paused");

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!design && !error && <Skeleton label="Loading the lesson" rows={4} />}

        {design && (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <Link href="/teacher" className="text-sm text-pencil underline underline-offset-4 hover:text-ink">
                  All lessons
                </Link>
                <h1 className="mt-1 font-serif text-2xl font-semibold text-ink">{design.title}</h1>
                <p className="text-sm">
                  {design.status === "draft" ? (
                    <span className="font-semibold text-amber">
                      Draft{design.version > 1 ? `, version ${design.version}` : ""}. Students
                      {design.approved_version_id ? " still get the approved version." : " can't use it yet."}
                    </span>
                  ) : (
                    <span className="font-semibold text-tick">Approved, version {design.version}</span>
                  )}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {live && (
                  <Link
                    href={`/teacher/live/${live.lesson_id}`}
                    className="inline-flex h-10 items-center rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-4 text-sm font-semibold text-ink hover:border-ink"
                  >
                    Open live lesson ({live.class_label})
                  </Link>
                )}
                {design.status === "draft" && (
                  <Button
                    variant={runnable ? "quiet" : "primary"}
                    onClick={approve}
                    disabled={busy !== null || design.missing.length > 0}
                    title={design.missing.length ? `Still needs ${design.missing.join(", ")}` : undefined}
                  >
                    {busy === "approve" ? "Approving…" : "Approve lesson"}
                  </Button>
                )}
                {runnable && classes && classes.length > 0 && (
                  <>
                    <label htmlFor="run-class" className="sr-only">
                      Class
                    </label>
                    <select
                      id="run-class"
                      value={classId || classes[0].id}
                      onChange={(e) => setClassId(e.target.value)}
                      className="h-10 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink"
                    >
                      {classes.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label} ({c.students})
                        </option>
                      ))}
                    </select>
                    <Button onClick={run} disabled={busy !== null}>
                      {busy === "run" ? "Starting…" : "Start with this class"}
                    </Button>
                  </>
                )}
              </div>
            </div>

            {actionError && (
              <div className="mb-4">
                <ErrorNote>{actionError}</ErrorNote>
              </div>
            )}
            {design.status === "draft" && design.missing.length > 0 && design.messages.length > 0 && (
              <div className="mb-4">
                <Notice tone="amber">Before you can approve it, the lesson needs {design.missing.join(", ")}.</Notice>
              </div>
            )}

            <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <section
                aria-label="Conversation with the class agent"
                className="flex h-[70vh] min-h-[28rem] flex-col rounded-[var(--radius-sheet)] border border-rule bg-paper p-4 lg:sticky lg:top-4 lg:h-[calc(100vh-9rem)]"
              >
                <AgentChat
                  className="h-full"
                  lines={lines}
                  pending={pending !== null}
                  pendingText="Working on the lesson brief…"
                  onSend={send}
                  onFiles
                  chips={design.messages.length > 0 ? CHIPS : []}
                  placeholder="Tell the agent what you want, or how to change it"
                  error={chatError}
                  autoFocus
                  empty="Describe the lesson: the topic, who it's for, what they already know, how long you have, and anything the agent must or mustn't do."
                />
              </section>
              <LessonBriefView design={design} />
            </div>
          </>
        )}
      </main>
    </>
  );
}
