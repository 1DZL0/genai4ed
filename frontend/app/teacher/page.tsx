"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ApiError, threadApi, type Thread, type ThreadAction } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { LiveStrip, ThreadCardView } from "@/components/cards";
import { LessonsPanel } from "@/components/lessons-panel";
import { Button, ErrorNote, Skeleton } from "@/components/ui";

/**
 * The teacher's whole interface: a conversation, and the one thing they are looking at.
 * Each side scrolls on its own, so the card stays put while they talk and the composer stays at the bottom.
 */

const STARTERS = [
  "Teach 8C about photosynthesis in 30 minutes. They did cell biology last week. Hints are fine, but never give the final answer.",
  "Year 9 English: practise writing an argumentative paragraph, 40 minutes. The agent must never write it for them.",
  "A 20-minute check on solving linear equations with the unknown on both sides.",
];

const CARD_NAMES: Record<string, string> = {
  lesson: "The lesson",
  lessons: "Your lessons",
  class: "The class",
  student: "The student",
  outcomes: "Outcomes",
};

export default function TeacherThread() {
  const me = useSignedIn("teacher");
  const { data, error, mutate, isLoading } = useSWR<Thread>(
    me ? "teacher-thread" : null,
    threadApi.read,
    { refreshInterval: 8000 },
  );

  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [clearing, setClearing] = useState(false);
  // Narrow screens show one side at a time.
  const [onCard, setOnCard] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const shown = useRef<string | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const messages = (data?.messages ?? []).filter((m) => m.text);
  const count = messages.length;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [count, sending]);

  const showing = data?.showing ?? null;
  const cardKey = showing
    ? [showing.type, "lesson_id" in showing ? showing.lesson_id : "", "student_id" in showing ? showing.student_id : ""].join(":")
    : null;
  useEffect(() => {
    // A new card starts at its top, whatever the last one was scrolled to.
    if (cardKey && shown.current !== null && shown.current !== cardKey && cardRef.current) {
      cardRef.current.scrollTop = 0;
      cardRef.current.focus();
    }
    shown.current = cardKey;
  }, [cardKey]);

  if (!me) return null;

  async function send() {
    const said = text.trim();
    const attached = files;
    if (busy || (!said && attached.length === 0)) return;
    setFailure(null);
    setText("");
    setFiles([]);
    setSending(said || `Attached ${attached.map((f) => f.name).join(", ")}`);
    setBusy(true);
    try {
      let latest: Thread | undefined;
      for (const file of attached) latest = await threadApi.attach(file);
      if (said || attached.length === 0) {
        latest = await threadApi.say(said || "Build a lesson from what I've attached.");
      }
      if (latest) await mutate(latest, { revalidate: false });
    } catch (e) {
      setFailure((e as ApiError).message);
      setText(said);
      await mutate();
    } finally {
      setSending(null);
      setBusy(false);
      boxRef.current?.focus();
    }
  }

  async function act(action: ThreadAction) {
    setFailure(null);
    setBusy(true);
    try {
      await mutate(await threadApi.act(action), { revalidate: false });
      if (action.action !== "clear") setOnCard(true);
    } catch (e) {
      setFailure((e as ApiError).message);
      await mutate();
    } finally {
      setBusy(false);
      setClearing(false);
    }
  }

  const focus = data?.focus;
  const blank = !isLoading && count === 0 && !sending && !showing;
  const link =
    "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink disabled:opacity-50";

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader me={me} />
      {data && (
        <LiveStrip
          rows={data.strip}
          act={act}
          busy={busy}
          showingSession={showing && "session_id" in showing ? showing.session_id : null}
        />
      )}

      <div className="no-print shrink-0 border-b border-rule bg-sheet">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-sm sm:px-6">
          <h1 className="min-w-0 truncate text-sm font-normal text-pencil">
            {focus ? (
              <>
                Working on{" "}
                <button
                  disabled={busy}
                  onClick={() => act({ action: "show_lesson", lesson_id: focus.lesson_id })}
                  className="font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                >
                  {focus.title}
                </button>
              </>
            ) : (
              "Your lessons and your class agent"
            )}
          </h1>
          <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
            <button onClick={() => setBrowsing(true)} className={link}>
              My lessons
            </button>
            {clearing ? (
              <span className="flex items-center gap-2 text-ink">
                Clear the conversation? Your lessons and records are kept.
                <Button
                  size="sm"
                  variant="red"
                  disabled={busy}
                  onClick={() => act({ action: "clear" })}
                >
                  Clear it
                </Button>
                <Button size="sm" variant="plain" onClick={() => setClearing(false)}>
                  Keep it
                </Button>
              </span>
            ) : (
              <button onClick={() => setClearing(true)} className={link}>
                Clear
              </button>
            )}
          </span>
        </div>
      </div>

      {showing && (
        <div
          role="tablist"
          aria-label="Talking, or looking at something"
          className="no-print flex shrink-0 gap-1 border-b border-rule bg-sheet px-4 sm:px-6 lg:hidden"
        >
          {[
            { id: "talk", label: "Conversation", card: false },
            { id: "card", label: CARD_NAMES[showing.type] ?? "On screen", card: true },
          ].map((tab) => (
            <button
              key={tab.id}
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={onCard === tab.card}
              aria-controls={`panel-${tab.id}`}
              tabIndex={onCard === tab.card ? 0 : -1}
              onClick={() => setOnCard(tab.card)}
              onKeyDown={(e) => {
                if (e.key === "ArrowRight" || e.key === "ArrowLeft") setOnCard(!onCard);
              }}
              className={`border-b-2 px-3 py-2 text-sm font-semibold ${
                onCard === tab.card ? "border-ink text-ink" : "border-transparent text-pencil"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      <main className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 gap-8 px-4 sm:px-6">
        <section
          id="panel-talk"
          role={showing ? "tabpanel" : undefined}
          aria-labelledby={showing ? "tab-talk" : undefined}
          aria-label={showing ? undefined : "Your conversation"}
          className={`min-h-0 min-w-0 flex-1 flex-col ${showing && onCard ? "hidden lg:flex" : "flex"}`}
        >
          {blank ? (
            <div className="flex flex-1 flex-col justify-center overflow-y-auto py-8">
              <h2 className="font-serif text-3xl font-semibold text-ink">
                What do you want to teach?
              </h2>
              <p className="mt-2 max-w-xl text-base text-pencil">
                Describe it the way you&apos;d tell a colleague: the topic, the class, how long, and
                how the agent should behave. Attach slides or a worksheet if you have them.
                Everything else happens here too — starting the lesson, seeing who needs you,
                confirming outcomes.
              </p>
              <ul className="mt-6 space-y-2">
                {STARTERS.map((s) => (
                  <li key={s}>
                    <button
                      onClick={() => {
                        setText(s);
                        boxRef.current?.focus();
                      }}
                      className="w-full rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3 text-left text-sm text-pencil hover:border-ink hover:text-ink"
                    >
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            /* role="log" on the list itself would replace its list semantics and orphan every item, so the live region wraps the list. */
            <div
              role="log"
              aria-live="polite"
              aria-label="Your conversation with the class agent"
              tabIndex={0}
              className="min-h-0 flex-1 overflow-y-auto py-6 focus:outline-none"
            >
              <ol className="space-y-5">
                {isLoading && !data && (
                  <li>
                    <Skeleton label="Opening your thread" rows={3} />
                  </li>
                )}
                {messages.map((m) => (
                  <li key={m.id}>
                    {m.role === "teacher" && (
                      <div className="flex justify-end">
                        <p className="max-w-[85%] rounded-[var(--radius-sheet)] bg-sunken px-4 py-2.5 text-base whitespace-pre-line text-ink">
                          {m.text}
                        </p>
                      </div>
                    )}
                    {m.role === "agent" && (
                      <p className="max-w-[92%] text-base whitespace-pre-line text-ink">{m.text}</p>
                    )}
                    {m.role === "event" && <p className="text-center text-xs text-faint">{m.text}</p>}
                  </li>
                ))}
                {sending && (
                  <li className="space-y-2">
                    <div className="flex justify-end">
                      <p className="max-w-[85%] rounded-[var(--radius-sheet)] bg-sunken px-4 py-2.5 text-base whitespace-pre-line text-faint">
                        {sending}
                      </p>
                    </div>
                    <p className="flex items-center gap-2 text-sm text-pencil">
                      <span aria-hidden className="size-2 animate-pulse rounded-full bg-pencil" />
                      Reading that and working it out. It takes a few seconds.
                    </p>
                  </li>
                )}
              </ol>
              <div ref={endRef} />
            </div>
          )}

          <div className="no-print shrink-0 border-t border-rule bg-paper pt-3 pb-4">
            {error && !data && (
              <div className="mb-2">
                <ErrorNote>{(error as ApiError).message}</ErrorNote>
              </div>
            )}
            {failure && (
              <div className="mb-2">
                <ErrorNote>{failure}</ErrorNote>
              </div>
            )}
            {files.length > 0 && (
              <ul className="mb-2 flex flex-wrap gap-2" aria-label="Files to send">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${i}`}
                    className="flex items-center gap-2 rounded-full bg-sunken px-3 py-1 text-xs text-ink"
                  >
                    {f.name}
                    <button
                      type="button"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
                      className="text-pencil hover:text-ink"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
              className="flex flex-wrap items-end gap-2"
            >
              <input
                ref={fileRef}
                type="file"
                aria-label="Choose teaching material to attach"
                multiple
                accept=".pdf,.docx,.pptx,.txt,.md,image/png,image/jpeg,image/webp,image/gif"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => {
                  setFiles((all) => [...all, ...Array.from(e.target.files ?? [])].slice(0, 10));
                  e.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="quiet"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
                className="h-11 shrink-0"
                aria-label="Attach teaching material"
              >
                Attach
              </Button>
              <label htmlFor="thread-composer" className="sr-only">
                Write to the class agent
              </label>
              <textarea
                id="thread-composer"
                ref={boxRef}
                rows={1}
                value={text}
                autoFocus
                onChange={(e) => {
                  setText(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
                  e.target.style.overflowY = e.target.scrollHeight > 200 ? "auto" : "hidden";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Tell the agent what to teach, or ask about a class…"
                className="order-first min-h-11 min-w-0 flex-1 basis-full resize-none overflow-y-hidden rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 py-2.5 text-base text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none sm:order-none sm:basis-auto"
              />
              <Button
                type="submit"
                disabled={busy || (!text.trim() && files.length === 0)}
                className="ml-auto h-11 shrink-0 px-5 sm:ml-0"
              >
                {sending ? "Sending…" : "Send"}
              </Button>
            </form>
          </div>
        </section>

        {(showing || sending) && (
          <section
            ref={cardRef}
            tabIndex={0}
            id="panel-card"
            role="tabpanel"
            aria-labelledby="tab-card"
            aria-label="What you're looking at"
            aria-busy={busy || Boolean(sending)}
            className={`min-h-0 w-full overflow-y-auto py-6 focus:outline-none lg:w-[26rem] lg:shrink-0 ${
              onCard ? "block" : "hidden lg:block"
            }`}
          >
            {showing ? (
              <div className={busy ? "opacity-60 transition-opacity" : undefined}>
                <ThreadCardView card={showing} act={act} busy={busy} />
              </div>
            ) : (
              <div className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                <Skeleton label="The agent is working on your lesson" rows={4} />
              </div>
            )}
          </section>
        )}
      </main>

      {browsing && <LessonsPanel onClose={() => setBrowsing(false)} act={act} busy={busy} />}
    </div>
  );
}
