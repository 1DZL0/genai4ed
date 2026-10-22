"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import useSWR, { mutate as refresh } from "swr";
import { ApiError, threadApi, type Thread, type ThreadAction } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { Shell } from "@/components/app-header";
import { LiveStrip, ThreadCardView } from "@/components/cards";
import { Composer, Said, Thinking } from "@/components/chat";
import { LessonsPanel, LessonsSide } from "@/components/lessons-panel";
import { Button, ErrorNote, Skeleton } from "@/components/ui";
import { APPROACHES } from "@/lib/approaches";

/**
 * The teacher's whole interface: a conversation with the class agent, and the one thing
 * they are looking at. It opens as a question and a box to answer it in; once there is
 * something to look at it sits beside the talk, and each side scrolls on its own.
 */

const STARTERS = [
  {
    title: "Percentages of amounts",
    meta: "Year 8, 30 minutes",
    text: "Year 8 maths, 30 minutes: percentages of amounts. 1) Recap 10% and 50% of £80. 2) Find 5% of £80 by halving 10%. 3) 15%, 25% and 40% of £60. 4) A £60 jumper has 25% off, what does it cost now? Hints are fine, never give the final answer, and tell me if anyone seems upset.",
  },
  {
    title: "Adding fractions",
    meta: "Year 7, 20 minutes",
    text: "Year 7 maths, 20 minutes: adding fractions with different denominators. 1) 1/2 + 1/4. 2) 1/3 + 1/6. 3) 2/5 + 1/2. Let them try twice before any worked step.",
  },
  {
    title: "Times-tables check",
    meta: "Year 5, 15 minutes",
    text: "A 15-minute times-tables check for year 5: ten questions from the 6, 7 and 8 times tables, then two word problems.",
  },
];

const CARD_NAMES: Record<string, string> = {
  lesson: "The lesson",
  lessons: "Your lessons",
  class: "Your class",
  student: "One student",
  outcomes: "End of the lesson",
};

/** What the right-hand side is showing, said above it, so it never reads as more chat. */
const CARD_HINTS: Record<string, string> = {
  lesson: "Builds up as you talk. Students see nothing until you approve it.",
  lessons: "Everything you have made. Press one to open it.",
  class: "Who needs you and how everyone is getting on. It updates by itself.",
  student: "Their work, and what you can tell the agent to do with them.",
  outcomes: "How the class did, and a note on each student for you to check.",
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
  // Written while the agent was still answering: sent the moment it has.
  const [queued, setQueued] = useState<string | null>(null);
  const queue = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  // Two teaching-approach starters behind a small link: a side comparison, not the main road.
  const [approaches, setApproaches] = useState(false);
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
    ? [
        showing.type,
        "lesson_id" in showing ? showing.lesson_id : "",
        "student_id" in showing ? showing.student_id : "",
      ].join(":")
    : null;
  useEffect(() => {
    // A new card starts at its top, whatever the last one was scrolled to.
    if (
      cardKey &&
      shown.current !== null &&
      shown.current !== cardKey &&
      cardRef.current
    ) {
      cardRef.current.scrollTop = 0;
      cardRef.current.focus();
    }
    shown.current = cardKey;
  }, [cardKey]);

  // A lesson's "Summary" link on the Classes page lands here as ?outcomes=<session_id>: open
  // that summary once, and take the query off so a reload does not open it again.
  const openOutcomes = useEffectEvent((sessionId: string) => {
    void act({ action: "show_outcomes", session_id: sessionId });
  });
  useEffect(() => {
    if (!me) return;
    const sessionId = new URLSearchParams(window.location.search).get("outcomes");
    if (!sessionId) return;
    window.history.replaceState(null, "", "/teacher");
    openOutcomes(sessionId);
  }, [me]);

  if (!me) return null;

  /** What is in the box, or `external` words (a queued message, a quick choice). */
  async function send(external?: string) {
    const said = (external ?? text).trim();
    const attached = external === undefined ? files : [];
    if (!said && attached.length === 0) return;
    if (busy) {
      // Held, not dropped: it goes as soon as the agent has answered.
      if (said) {
        queue.current = said;
        setQueued(said);
        if (external === undefined) setText("");
      }
      return;
    }
    setFailure(null);
    if (external === undefined) {
      setText("");
      setFiles([]);
    }
    setSending(said || `Attached ${attached.map((f) => f.name).join(", ")}`);
    setBusy(true);
    try {
      let latest: Thread | undefined;
      for (const file of attached) latest = await threadApi.attach(file);
      if (said || attached.length === 0) {
        latest = await threadApi.say(
          said || "Build a lesson from what I've attached.",
        );
      }
      if (latest) await mutate(latest, { revalidate: false });
    } catch (e) {
      setFailure((e as ApiError).message);
      // Back in the box to send again, without overwriting anything written since.
      setText((now) => now || said);
      await mutate();
    } finally {
      setSending(null);
      setBusy(false);
      boxRef.current?.focus();
      void refresh("thread-lessons");
      sendQueued();
    }
  }

  /** The message held while the agent was busy. This render's `busy` was false when the
   * finished request began, so the held one is sent rather than held again. */
  function sendQueued() {
    const next = queue.current;
    if (!next) return;
    queue.current = null;
    setQueued(null);
    void send(next);
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
      void refresh("thread-lessons");
      sendQueued();
    }
  }

  const focus = data?.focus;
  const blank = !isLoading && count === 0 && !sending && !showing;
  // With a card beside it, the talk leans towards it, so it sits near the middle of the screen.
  const lane = showing || sending ? "ml-auto lg:mr-8" : "mx-auto";
  // While a class is being taught the list of lessons steps aside and the class gets the room.
  const teaching = showing?.type === "class" || showing?.type === "student";
  const link =
    "text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink disabled:opacity-50";
  const chip =
    "rounded-full border border-rule-strong bg-sheet px-3.5 py-1.5 font-semibold text-ink hover:border-ink disabled:opacity-50";

  const composer = (
    <>
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
      <input
        ref={fileRef}
        type="file"
        aria-label="Choose teaching material to attach"
        multiple
        accept=".pdf,.docx,.pptx,.txt,.md,image/png,image/jpeg,image/webp,image/gif"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          // Read them now: clearing the input empties e.target.files before React runs the updater.
          const picked = Array.from(e.target.files ?? []);
          e.target.value = "";
          setFiles((all) => [...all, ...picked].slice(0, 10));
        }}
      />
      <Composer
        id="thread-composer"
        label="Write to the class agent"
        value={text}
        onChange={setText}
        onSubmit={() => send()}
        boxRef={boxRef}
        placeholder="Tell the agent what to teach, or ask about a class"
        maxLength={6000}
        canSend={Boolean(text.trim()) || (!busy && files.length > 0)}
        actions={
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className={link}
          >
            Attach teaching material
          </button>
        }
      />
    </>
  );

  return (
    <Shell me={me}>
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {data && (
        <LiveStrip
          rows={data.strip}
          act={act}
          busy={busy}
          showingSession={
            showing && "session_id" in showing ? showing.session_id : null
          }
        />
      )}

      <div className="no-print shrink-0 border-b border-rule bg-sheet">
        <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-sm sm:px-6">
          {/* The title shrinks and ends in "...", never the words before it: inside one
              truncated line the whole name gave way to the ellipsis on a phone. */}
          <h1 className="flex min-w-0 items-baseline gap-x-1 text-sm font-normal text-pencil">
            {focus ? (
              <>
                <span className="shrink-0">Working on</span>
                <button
                  disabled={busy}
                  onClick={() =>
                    act({ action: "show_lesson", lesson_id: focus.lesson_id })
                  }
                  className="min-w-0 truncate font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                >
                  {focus.title}
                </button>
              </>
            ) : (
              <span className="truncate">Talking with your class agent</span>
            )}
          </h1>
          <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
            <button onClick={() => setBrowsing(true)} className={chip}>
              All my lessons
            </button>
            {clearing ? (
              <span className="flex items-center gap-2 text-ink">
                Start a new conversation? Your lessons and records are kept.
                <Button
                  size="sm"
                  variant="red"
                  disabled={busy}
                  onClick={() => act({ action: "clear" })}
                >
                  Start new
                </Button>
                <Button
                  size="sm"
                  variant="plain"
                  onClick={() => setClearing(false)}
                >
                  Keep it
                </Button>
              </span>
            ) : (
              <button onClick={() => setClearing(true)} className={chip}>
                New conversation
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
            {
              id: "card",
              label: CARD_NAMES[showing.type] ?? "On screen",
              card: true,
            },
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
                if (e.key === "ArrowRight" || e.key === "ArrowLeft")
                  setOnCard(!onCard);
              }}
              className={`border-b-2 px-3 py-2 text-sm font-semibold ${
                onCard === tab.card
                  ? "border-ink text-ink"
                  : "border-transparent text-pencil"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      <main className="flex w-full min-h-0 flex-1 gap-6 px-4 sm:px-6">
        {!teaching && (
          <LessonsSide
            act={act}
            busy={busy}
            current={focus?.lesson_id ?? null}
            from={showing || sending ? "2xl:flex" : "lg:flex"}
          />
        )}
        <section
          id="panel-talk"
          role={showing ? "tabpanel" : undefined}
          aria-labelledby={showing ? "tab-talk" : undefined}
          aria-label={showing ? undefined : "Your conversation"}
          className={`min-h-0 min-w-0 flex-1 flex-col ${showing && onCard ? "hidden lg:flex" : "flex"}`}
        >
          {blank ? (
            // Auto margins centre it when there is room; on a short screen it starts at the top
            // and scrolls, where justify-center pushed the heading out of reach above the box.
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto py-8">
              <div className="m-auto w-full max-w-3xl">
                <h2 className="text-center font-serif text-3xl font-semibold text-ink">
                  What do you want to teach?
                </h2>
                <p className="mx-auto mt-3 max-w-xl text-center text-base text-pencil">
                  Write the lesson as you&apos;d teach it: the steps, the
                  questions, and how the agent should behave. It keeps your
                  words and fills in only what you leave out.
                </p>
                <div className="no-print mt-8">{composer}</div>
                <p className="mt-8 text-sm text-pencil">
                  Or start from one of these
                </p>
                <ul className="mt-2 grid gap-2 sm:grid-cols-3">
                  {STARTERS.map((s) => (
                    <li key={s.title}>
                      <button
                        onClick={() => {
                          setText(s.text);
                          boxRef.current?.focus();
                        }}
                        className="flex h-full w-full flex-col items-start rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3 text-left hover:border-ink"
                      >
                        <span className="block font-semibold text-ink">
                          {s.title}
                        </span>
                        <span className="block text-xs text-pencil">
                          {s.meta}
                        </span>
                        <span className="mt-2 line-clamp-3 text-sm text-pencil">
                          {s.text}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="mt-6 text-xs text-pencil">
                  <button
                    type="button"
                    onClick={() => setApproaches(!approaches)}
                    className="underline decoration-rule-strong underline-offset-4 hover:text-ink"
                  >
                    Comparing two teaching approaches?
                  </button>
                </p>
                {approaches && (
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                    {Object.entries(APPROACHES).map(([key, a]) => (
                      <li key={key}>
                        <button
                          disabled={busy}
                          onClick={() => {
                            void act({ action: "start_approach", text: key });
                            boxRef.current?.focus();
                          }}
                          className="flex h-full w-full flex-col items-start rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3 text-left hover:border-ink"
                        >
                          <span className="block font-semibold text-ink">{a.name}</span>
                          <span className="mt-1 block text-sm text-pencil">{a.short}</span>
                          <span className="mt-2 block text-xs text-pencil">
                            Starts a new lesson taught this way. Then describe it as usual; the agent builds it to the approach.
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : (
            <>
              {showing && (
                <PanelTitle
                  title="Chat with the class agent"
                  hint="Tell it what to teach, answer its questions, or ask about your class."
                  className={`${lane} w-full max-w-3xl`}
                />
              )}
              {/* role="log" on the list itself would replace its list semantics and orphan every item, so the live region wraps the list. */}
              <div
                role="log"
                aria-live="polite"
                aria-label="Your conversation with the class agent"
                tabIndex={0}
                className={`${lane} min-h-0 w-full max-w-3xl flex-1 overflow-y-auto py-6 focus:outline-none`}
              >
                <ol className="space-y-6">
                  {isLoading && !data && (
                    <li>
                      <Skeleton label="Opening your thread" rows={3} />
                    </li>
                  )}
                  {messages.map((m) => (
                    <li key={m.id}>
                      <Said
                        who={
                          m.role === "teacher"
                            ? "me"
                            : m.role === "agent"
                              ? "agent"
                              : "note"
                        }
                      >
                        {m.text}
                      </Said>
                    </li>
                  ))}
                  {sending && (
                    <li className="space-y-6">
                      <Said who="me" unsent>
                        {sending}
                      </Said>
                      <Thinking label="Reading that and working it out. It takes a few seconds." />
                    </li>
                  )}
                  {queued && (
                    <li>
                      <Said who="me" unsent>
                        {queued}
                      </Said>
                      <p className="mt-1 text-right text-xs text-pencil">
                        Sends as soon as the agent has answered.
                      </p>
                    </li>
                  )}
                </ol>
                <div ref={endRef} />
              </div>

              <div
                className={`no-print ${lane} w-full max-w-3xl shrink-0 pt-2 pb-4`}
              >
                {composer}
              </div>
            </>
          )}
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
            className={`min-h-0 w-full overflow-y-auto pb-6 focus:outline-none lg:w-[36rem] lg:shrink-0 lg:border-l lg:border-rule lg:pl-6 xl:w-[42rem] ${
              onCard ? "block" : "hidden lg:block"
            }`}
          >
            <PanelTitle
              title={showing ? (CARD_NAMES[showing.type] ?? "On screen") : "The lesson"}
              hint={showing ? CARD_HINTS[showing.type] : CARD_HINTS.lesson}
            />
            {showing ? (
              <div
                className={busy ? "opacity-60 transition-opacity" : undefined}
              >
                <ThreadCardView
                  card={showing}
                  act={act}
                  busy={busy}
                  say={(words) => void send(words)}
                />
              </div>
            ) : (
              <div className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4">
                <Skeleton
                  label="The agent is working on your lesson"
                  rows={4}
                />
              </div>
            )}
          </section>
        )}
      </main>

      {browsing && (
        <LessonsPanel
          onClose={() => setBrowsing(false)}
          act={act}
          busy={busy}
        />
      )}
    </div>
    </Shell>
  );
}

/** The name of one side of the page, on wide screens where both sides show at once. */
function PanelTitle({
  title,
  hint,
  className = "",
}: {
  title: string;
  hint: string;
  className?: string;
}) {
  return (
    <div
      className={`sticky top-0 z-10 hidden shrink-0 border-b border-rule bg-paper pt-4 pb-2 lg:block ${className}`}
    >
      <h2 className="text-base font-bold text-ink">{title}</h2>
      <p className="text-xs text-pencil">{hint}</p>
    </div>
  );
}
