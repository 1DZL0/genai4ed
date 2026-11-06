"use client";

import { use, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { agentApi, ApiError, type Intent, type Learn, type LearnMove } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader } from "@/components/app-header";
import { AgentChat, type ChatLine } from "@/components/agent-chat";
import { COLUMN } from "@/components/chat";
import { Button, ErrorNote, Skeleton, SubjectName, TimerBadge } from "@/components/ui";
import { EndedScreen, PausedScreen, TimeUpScreen } from "@/components/lesson-screens";

/** What went wrong, in words a pupil can act on: the server's own message when there is one,
 * plain words when the connection itself dropped. */
function plainError(e: unknown): string {
  if (e instanceof ApiError && e.message) return e.message;
  return "You're offline or the connection dropped. Your words are still in the box; try again in a moment.";
}

// Often enough that a pause, an ending or a note from the teacher shows up while the student is working.
const POLL_MS = 8000;

// How each part looks in the strip at the top, by its state: the circle, the text, and the
// words a screen reader says after its name.
const PART_LOOK: Record<Learn["steps"][number]["state"], { circle: string; tone: string; said: string }> = {
  done: { circle: "bg-tick-wash text-tick", tone: "text-ink", said: ", done" },
  current: { circle: "bg-ink text-white", tone: "font-semibold text-ink", said: ", now" },
  parked: { circle: "border-2 border-amber text-amber", tone: "text-ink", said: ", left for later" },
  todo: { circle: "border border-rule-strong text-pencil", tone: "text-pencil", said: ", to come" },
};

// Three buttons, one row on a phone. After a wrong try the first one asks about that try.
const CHIPS: { label: string; intent: Intent }[] = [
  { label: "I don't understand", intent: "dont_understand" },
  { label: "Explain it another way", intent: "another_way" },
  { label: "Give me an example", intent: "example" },
];
const CHIPS_AFTER_WRONG: { label: string; intent: Intent }[] = [
  { label: "Why is it wrong?", intent: "why_wrong" },
  ...CHIPS.slice(1),
];

/** "now", "after one more try", "after 3 more tries". */
function inTries(n: number) {
  return n === 0 ? "now" : n === 1 ? "after one more try" : `after ${n} more tries`;
}

/** What help the rules allow right now, as one quiet line: it changes as the rules let more
 * through, which is how a pupil sees the ladder is real. */
function helpLine(h: Learn["help"]): string {
  const answer =
    h.answer_in === null
      ? "Your tutor will not give you the answer."
      : h.answer_in === 0
        ? "You can ask for the answer."
        : `You can have the answer ${inTries(h.answer_in)}.`;
  if (h.ladder) return `Help comes one kind at a time, a bit more after each try. ${answer}`;
  if (!h.hint) return `No hints in this lesson, so it is your own working. ${answer}`;
  const now = h.worked_step_in === 0 ? "a hint, an example or a worked step" : "a hint or an example";
  const later =
    h.worked_step_in && h.worked_step_in > 0
      ? ` ${inTries(h.worked_step_in).replace(/^after/, "After")} you can see a worked step.`
      : "";
  return `You can ask for ${now}.${later} ${answer}`;
}

/** The lesson is a conversation with the class agent, and the page is little else. */
export default function StudentLesson({ params }: PageProps<"/student/[sessionId]">) {
  const { sessionId } = use(params);
  const me = useSignedIn("student");
  // The lesson was live on this screen at some point: see onSuccess below.
  const [wasLive, setWasLive] = useState(false);
  const { data, error: loadError, mutate } = useSWR<Learn>(
    me ? ["learn", sessionId] : null,
    () => agentApi.learn(sessionId),
    {
      refreshInterval: POLL_MS,
      keepPreviousData: true,
      // Remembered from each fetch, so a lesson that ends under the pupil shows the ended
      // screen while one opened after it ended goes straight to the record.
      onSuccess: (view) => {
        if (view.status === "open" || view.status === "paused") setWasLive(true);
      },
    },
  );
  const [pending, setPending] = useState<string | null>(null);
  // Moving to another part: the tutor is opening it.
  const [moving, setMoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  // Whether the last thing sent was a help button: the reply to one may be rated.
  const [lastWasChip, setLastWasChip] = useState(false);
  // The opening failed (the model was busy, or the class was paused a moment): the box opens
  // so the student is not locked out, and the opening is tried again on a later refresh.
  const [openFailed, setOpenFailed] = useState(false);
  const started = useRef(false);
  // The lesson was live on this screen: when it ends under the pupil, say so before the
  // record; a lesson opened after it ended just shows the record.
  const [lookedBack, setLookedBack] = useState(false);

  // The agent opens the lesson the first time it's seen. Until the agent has said something:
  // an "Ask my teacher" note left while the class was paused does not count as opened.
  useEffect(() => {
    if (!data || started.current || data.lines.some((l) => l.who === "agent") || !data.can_talk)
      return;
    started.current = true;
    agentApi
      .learnStart(sessionId)
      .then((view) => {
        setOpenFailed(false);
        return mutate(view, { revalidate: false });
      })
      .catch((e: ApiError) => {
        setError(e.message);
        setOpenFailed(true);
        window.setTimeout(() => {
          started.current = false;
        }, 10_000);
      });
  }, [data, sessionId, mutate]);

  if (!me) return null;

  /** False when it did not go through, so the box gives the words back. */
  async function send(text: string, intent?: string): Promise<boolean> {
    setError(null);
    setLastWasChip(Boolean(intent));
    setPending(
      text || [...CHIPS, ...CHIPS_AFTER_WRONG].find((c) => c.intent === intent)?.label || "",
    );
    try {
      const view = await agentApi.learnSay(sessionId, text, intent as Intent | undefined);
      await mutate(view, { revalidate: false });
      return true;
    } catch (e) {
      setError(plainError(e));
      await mutate();
      return false;
    } finally {
      setPending(null);
    }
  }

  /** Go to another part, or leave the one they are on for later. The tutor then opens it. */
  async function goTo(move: LearnMove) {
    setError(null);
    setLastWasChip(false);
    setMoving("to" in move ? `Opening part ${move.to + 1}` : "Opening the next part");
    try {
      await mutate(await agentApi.learnMove(sessionId, move), { revalidate: false });
    } catch (e) {
      setError(plainError(e));
      await mutate();
    } finally {
      setMoving(null);
    }
  }

  async function rate(lineId: string, helped: boolean) {
    try {
      await mutate(await agentApi.learnHelped(sessionId, lineId, helped), { revalidate: false });
    } catch (e) {
      setError(plainError(e));
    }
  }

  async function askTeacher() {
    // Off at once, so a double tap is one call for the teacher. After that the server says
    // whether the request is still open, so a reload keeps it off and Dealt with turns it on.
    setAsked(true);
    try {
      await mutate(await agentApi.learnAskTeacher(sessionId), { revalidate: false });
    } catch (e) {
      setError(plainError(e));
    } finally {
      setAsked(false);
    }
  }

  const lines: ChatLine[] = (data?.lines ?? []).map((l) => ({
    id: l.id,
    who: l.who === "student" ? "me" : l.who === "agent" ? "agent" : "note",
    text: l.text,
    helped: l.helped,
  }));
  if (pending) lines.push({ id: "pending", who: "me", text: pending });
  const opening = data && !data.lines.some((l) => l.who === "agent") && data.can_talk;
  const waiting = asked || Boolean(data?.asked_teacher);
  // Writing or moving: one thing at a time, so a move never lands under a reply.
  const busy = pending !== null || moving !== null;
  const closed = data?.status === "closed";
  const done = data?.steps.filter((s) => s.state === "done").length ?? 0;
  const total = data?.steps.length ?? 0;
  // From the server, which reads it from the records that outlive the chat: after the chat
  // is purged a student who took part still did.
  const tookPart = Boolean(data?.took_part) || (data?.lines ?? []).some((l) => l.who === "student");
  const help = data?.help;
  // The example button gives an example of a similar problem, whenever hints are allowed.
  // Once every step is done there is nothing to be stuck on, so the help buttons go.
  const chips = data?.can_talk && !data.completed
    ? (data.wrong_tries > 0 ? CHIPS_AFTER_WRONG : CHIPS).map((c) =>
        c.intent === "example" && help && !help.hint
          ? { ...c, label: "No examples in this lesson", disabled: true }
          : c,
      )
    : [];

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader me={me} />

      {data && (
        /* On a short screen (a phone with the keyboard up) the header gives way: the step list
           and the subject go, the task line keeps to one line, so the talk keeps its room. */
        <div className="shrink-0 border-b border-rule bg-sheet">
          <div
            className={`${COLUMN} flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-2.5 short:py-1.5`}
          >
            <h1 className="min-w-0 truncate font-serif text-lg font-semibold text-ink short:text-base">
              {data.title}
            </h1>
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-pencil">
              <span className="short:hidden">
                <SubjectName subject={data.subject} />
              </span>
              {data.steps.length > 0 && (
                <span className="figures">
                  {data.completed
                    ? "Finished"
                    : `Part ${data.step_index + 1} of ${data.steps.length}`}
                </span>
              )}
              {/* The one control that reaches a person: dark, apart from the help buttons. */}
              {!closed && data.can_talk && (
                <Button size="sm" variant="pillDark" onClick={askTeacher} disabled={waiting}>
                  {waiting ? "Your teacher knows you need them" : "Ask my teacher"}
                </Button>
              )}
              {/* The clock, top right: a small tablet the pupil can see from the corner of
                  their eye, amber for the last five minutes. */}
              {!data.completed && <TimerBadge closesAt={data.closes_at} status={data.status} />}
            </p>
          </div>
          {data.steps.length > 1 && (
            <ol aria-label="The parts of this lesson" className={`${COLUMN} flex flex-wrap gap-x-2 gap-y-1 pb-2.5 text-sm short:hidden`}>
              {data.steps.map((s, i) => {
                // A part they can go to is a button; the one they are on, or one not open yet, is not.
                const canGo = s.reachable && s.state !== "current" && data.can_talk && !busy;
                const look = PART_LOOK[s.state];
                const inner = (
                  <>
                    <span
                      aria-hidden="true"
                      className={`figures flex size-5 items-center justify-center rounded-full text-[11px] font-semibold ${look.circle}`}
                    >
                      {s.state === "done" ? "\u2713" : i + 1}
                    </span>
                    {s.name}
                    {s.state === "parked" && <span className="text-xs font-normal text-amber">later</span>}
                    <span className="sr-only">
                      {look.said}
                      {canGo ? ", go to this part" : ""}
                    </span>
                  </>
                );
                return (
                  <li key={i}>
                    {canGo ? (
                      <button
                        type="button"
                        onClick={() => goTo({ to: i })}
                        className={`flex items-center gap-1.5 rounded-full px-1.5 py-0.5 hover:bg-sunken ${look.tone}`}
                      >
                        {inner}
                      </button>
                    ) : (
                      <span
                        aria-current={s.state === "current" ? "step" : undefined}
                        className={`flex items-center gap-1.5 px-1.5 py-0.5 ${look.tone}`}
                      >
                        {inner}
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          {/* The question on the table stays here while the conversation scrolls under it. */}
          {!closed && (data.task || (data.can_leave && data.can_talk)) && (
            <div className={`${COLUMN} flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 pb-2.5 short:pb-1.5`}>
              {data.task ? (
                <p className="min-w-0 text-sm text-pencil short:truncate" title={data.task}>
                  Working on{" "}
                  <span className="font-semibold text-ink">
                    {data.steps[data.step_index]?.question || data.task}
                  </span>
                </p>
              ) : (
                <span />
              )}
              {/* Leave this part and come back to it: the next part still to do opens. */}
              {data.can_leave && data.can_talk && !data.completed && (
                <Button size="sm" variant="pill" onClick={() => goTo({ leave: data.step_index })} disabled={busy}>
                  Come back to this later
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {!data && (
        <main className={`${COLUMN} flex-1 py-8`}>
          {loadError ? (
            <ErrorNote>
              {[404, 422].includes((loadError as ApiError).status)
                ? "This lesson could not be found. Go back to your lessons and open it from there."
                : (loadError as ApiError).message}
            </ErrorNote>
          ) : (
            <Skeleton label="Loading your lesson" rows={4} />
          )}
        </main>
      )}

      {data && data.status === "paused" && <PausedScreen />}
      {data && data.status === "open" && data.time_up && <TimeUpScreen />}
      {data && closed && wasLive && !lookedBack && (
        <EndedScreen
          onLookBack={() => {
            setLookedBack(true);
            window.scrollTo({ top: 0 });
          }}
        />
      )}

      {data && (
        <main aria-label="Your lesson conversation" className="flex min-h-0 flex-1 flex-col">
          <AgentChat
            lines={lines}
            subject={data.subject}
            pending={busy || (Boolean(opening) && !openFailed)}
            pendingText={
              moving ?? (opening && !openFailed ? "Getting your lesson ready" : "Reading what you wrote")
            }
            onSend={send}
            chips={chips}
            placeholder={closed ? "This lesson has ended" : "Write your answer or ask a question"}
            disabled={!data.can_talk}
            above={
              closed && (
                <section
                  aria-label="How it went"
                  className="mb-6 rounded-[var(--radius-sheet)] border border-tick/50 bg-sheet px-5 py-4"
                >
                  <p className="text-xs font-semibold text-pencil">Your lesson is over</p>
                  <p className="mt-1 font-serif text-xl font-semibold text-ink">
                    {!tookPart && !data.result
                      ? "You did not take part in this lesson."
                      : total === 0
                        ? "Your conversation is saved."
                        : done === total
                          ? `You finished all ${total} steps.`
                          : done === 0
                            ? "You did not get to the first step this time."
                            : `You got through ${done} of ${total} steps.`}
                  </p>
                  {tookPart && total > 0 && (
                    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-sm" aria-label="The steps">
                      {data.steps.map((s, i) => (
                        <li key={i} className="flex items-center gap-1.5">
                          <span
                            aria-hidden="true"
                            className={`figures flex size-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                              s.state === "done"
                                ? "bg-tick-wash text-tick"
                                : "border border-rule-strong text-pencil"
                            }`}
                          >
                            {s.state === "done" ? "\u2713" : i + 1}
                          </span>
                          <span className={s.state === "done" ? "text-ink" : "text-pencil"}>
                            {s.name}
                            <span className="sr-only">{s.state === "done" ? ", done" : s.state === "current" ? ", you were on this one" : ", not reached"}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {/* A result the teacher confirmed is always shown, even one from before the
                      took-part rule, when an opening alone could be given an outcome. */}
                  {data.result ? (
                    <>
                      {data.result.out_of > 0 && (
                        <p className="figures mt-2 font-serif text-2xl font-semibold text-ink">
                          {data.result.total} / {data.result.out_of}
                        </p>
                      )}
                      {data.result.out_of > 0 && (
                        <ul className="mt-1 flex flex-wrap gap-x-4 text-sm text-pencil">
                          {data.result.criteria.map((c) => (
                            <li key={c.name} className="figures">
                              {c.name} {c.points} / {c.max}
                            </li>
                          ))}
                        </ul>
                      )}
                      {data.result.keep && (
                        <p className="mt-2 text-base text-ink">
                          <span className="font-semibold">What went well: </span>
                          {data.result.keep}
                        </p>
                      )}
                      {data.result.develop.length > 0 && (
                        <div className="mt-2 text-base text-ink">
                          <p className="font-semibold">To look at again:</p>
                          <ul className="list-disc pl-5">
                            {data.result.develop.map((d) => (
                              <li key={d}>{d}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {data.result.comment && (
                        <p className="mt-2 text-base text-ink">
                          Your teacher says: &ldquo;{data.result.comment}&rdquo;
                        </p>
                      )}
                      {!data.result.keep && data.result.develop.length === 0 && !data.result.comment && (
                        <p className="mt-2 text-sm text-pencil">Your teacher has looked at this lesson.</p>
                      )}
                    </>
                  ) : !tookPart ? null : (
                    <p className="mt-2 text-sm text-pencil">
                      Your teacher will add a note here once they have looked at your work.
                    </p>
                  )}
                </section>
              )
            }
            below={
              // Every step done while the lesson is still running; once it has ended the
              // box above the conversation says how it went.
              data.completed &&
              !closed && (
                <section
                  aria-label="Finished"
                  className="mt-6 rounded-[var(--radius-sheet)] border border-tick/50 bg-tick-wash px-5 py-4"
                >
                  <p className="text-xs font-semibold text-tick">Finished</p>
                  <p className="mt-1 font-serif text-xl font-semibold text-ink">
                    You finished every step. Well done.
                  </p>
                  <p className="mt-1 text-sm text-ink">Your teacher can see your work.</p>
                </section>
              )
            }
            notice={
              error ? (
                <ErrorNote>{error}</ErrorNote>
              ) : data.status === "paused" ? (
                <p className="text-amber">
                  Your teacher has paused the class. You can read back, and carry on when they
                  resume.
                </p>
              ) : data.completed && !closed ? (
                <p className="text-tick">
                  You&apos;ve finished the activity. You can still ask your tutor questions.
                </p>
              ) : !closed && help ? (
                <p className="text-pencil">{helpLine(help)}</p>
              ) : null
            }
            footnote={data.disclosure}
            onRate={rate}
            rateLatest={lastWasChip}
            // The symbols row is for lessons that need it; an English lesson does not.
            symbols={data.can_talk && /math|science|physics|chemistry|biology/i.test(data.subject)}
            // The ending box, then the mark, appear above the conversation: bring them into view.
            topKey={
              closed
                ? `closed:${data.result ? `${data.result.total}:${data.result.comment ?? ""}` : ""}`
                : undefined
            }
          />
        </main>
      )}
    </div>
  );
}
