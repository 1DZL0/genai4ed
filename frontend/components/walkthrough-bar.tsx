"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { agentApi, api, ApiError, type Walkthrough } from "@/lib/api";

/**
 * The guided walkthrough: a bar across the top that steps through one lesson
 * with a class of pretend students. Their messages go through the real class
 * agent, rules, checks and triage. Demo mode only; progress is kept in this browser.
 */

const KEY = "genai4ed-walkthrough-v2";
/** Asks the live lesson page to open one student's drawer. */
export const OPEN_STUDENT_EVENT = "genai4ed-open-student";
type State = { run: Walkthrough; step: number };

let cachedRaw: string | null = null;
let cachedState: State | null = null;
function read(): State | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedState = raw ? (JSON.parse(raw) as State) : null;
    } catch {
      cachedState = null;
    }
  }
  return cachedState;
}
function write(state: State | null) {
  try {
    if (state) window.localStorage.setItem(KEY, JSON.stringify(state));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the bar simply won't remember */
  }
  window.dispatchEvent(new Event(KEY));
}
function subscribe(onChange: () => void) {
  window.addEventListener(KEY, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(KEY, onChange);
    window.removeEventListener("storage", onChange);
  };
}

type Ctx = { run: Walkthrough; live: string; openStudent: (index: number) => void };
type Step = {
  title: string;
  text: string;
  go?: (w: Walkthrough) => string;
  action?: { label: string; run: (c: Ctx) => Promise<string | void> };
};

const STEPS: Step[] = [
  {
    title: "A lesson made by talking",
    text: "This lesson was made by describing it to the class agent (left). The brief on the right is what it will teach: objectives, the activity, and your rules compiled so the server can enforce them.",
    go: (w) => `/teacher/studio/${w.design_id}`,
  },
  {
    title: "Start it with a class",
    text: "The class 9B Walkthrough has six pretend students, each behaving like a different kind of student.",
    go: (w) => `/teacher/studio/${w.design_id}`,
    action: {
      label: "Start the lesson",
      run: async ({ run, live }) => {
        await api.startLesson(run.lesson_id);
        return live;
      },
    },
  },
  {
    title: "Students open the lesson",
    text: "Each student's lesson is a conversation with the agent. It greets them and sets the first question.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Let them open it",
      run: async ({ run, live }) => {
        await agentApi.live(run.lesson_id);
        await api.simulate(run.lesson_id, "open");
        return live;
      },
    },
  },
  {
    title: "The class works",
    text: "Students answer. The agent judges each answer against the brief and decides what to do next: follow up, hint, challenge or move on.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Let them answer",
      run: async ({ run, live }) => {
        await api.simulate(run.lesson_id, "work");
        return live;
      },
    },
  },
  {
    title: "Only what matters reaches you",
    text: "One student keeps trying to get the answer and two share a misconception. Ordinary things stay in the record; what needs you goes under Needs you, and patterns under Across the class.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Carry on",
      run: async ({ run, live }) => {
        await api.simulate(run.lesson_id, "push");
        return live;
      },
    },
  },
  {
    title: "Look at a student",
    text: "Open a student to see their steps, what the agent recorded and why. Reading the conversation itself is a separate, logged click.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Open the student who's testing the rules",
      run: async ({ openStudent }) => {
        openStudent(4);
      },
    },
  },
  {
    title: "Guide the agent for one student",
    text: "Type guidance in the student's panel, for example “Give them a simpler example first”. Only that student's agent uses it, from their next reply.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Open the unsure student",
      run: async ({ openStudent }) => {
        openStudent(1);
      },
    },
  },
  {
    title: "Ask the agent about the class",
    text: "Ask it anything about the lesson so far. It answers from the class record, naming students by pseudonym.",
    go: (w) => `/teacher/live/${w.lesson_id}`,
    action: {
      label: "Ask who's struggling",
      run: async ({ run, live }) => {
        await agentApi.askClass(run.lesson_id, "Who is struggling right now, and what should I do?");
        return live;
      },
    },
  },
  {
    title: "End and review",
    text: "The lesson ends. The agent suggests an outcome for each student from what they showed; you confirm or change each one.",
    go: (w) => `/teacher/live/${w.lesson_id}/review`,
    action: {
      label: "Finish and end the lesson",
      run: async ({ run }) => {
        await api.simulate(run.lesson_id, "finish");
        await api.setSessionState(run.lesson_id, "closed");
        return `/teacher/live/${run.lesson_id}/review`;
      },
    },
  },
];

export function WalkthroughBar() {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const { data: config } = useSWR("sign-in-config", api.signInConfig);
  const state = useSyncExternalStore(subscribe, read, () => null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const barRef = useRef<HTMLDivElement>(null);

  // Side panels start below the bar, so it never covers their heading or Close.
  const active = Boolean(config?.demo_sign_in && state);
  useEffect(() => {
    const root = document.documentElement;
    const el = barRef.current;
    if (!active || !el) {
      root.style.setProperty("--walkthrough-h", "0px");
      return;
    }
    const observer = new ResizeObserver(() =>
      root.style.setProperty("--walkthrough-h", `${el.offsetHeight}px`),
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      root.style.setProperty("--walkthrough-h", "0px");
    };
  }, [active]);

  if (!config?.demo_sign_in) return null;

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.beginWalkthrough();
      write({ run, step: 0 });
      setDone(false);
      router.push(STEPS[0].go!(run));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  function goTo(step: number) {
    if (!state) return;
    setError(null);
    setDone(false);
    write({ ...state, step });
    const target = STEPS[step].go?.(state.run);
    if (target) router.push(target);
  }

  async function act() {
    if (!state) return;
    const action = STEPS[state.step].action;
    if (!action) return;
    setBusy(true);
    setError(null);
    try {
      const target = await action.run({
        run: state.run,
        live: `/teacher/live/${state.run.lesson_id}`,
        openStudent: (index) => {
          const member = state.run.cast[index];
          if (member) {
            window.dispatchEvent(new CustomEvent(OPEN_STUDENT_EVENT, { detail: member.student_id }));
          }
        },
      });
      await mutate(() => true);
      if (target) router.push(target);
      setDone(true);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const barButton =
    "h-9 rounded-[var(--radius-control)] border px-3.5 text-sm font-bold whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-40";
  const quietLink = "h-9 px-2 text-sm text-[#B9C4D1] underline underline-offset-4 hover:text-white";

  if (!state) {
    return (
      <div className="no-print bg-ink px-4 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 py-2 text-sm">
          <span className="flex-1">
            Showing someone the platform? Walk through a lesson with a class of pretend students.
          </span>
          {error && <span className="text-[#F3B8B0]">{error}</span>}
          <button onClick={begin} disabled={busy} className={`${barButton} border-white bg-white text-ink`}>
            {busy ? "Setting up…" : "Start the walkthrough"}
          </button>
        </div>
      </div>
    );
  }

  const index = Math.min(state.step, STEPS.length - 1);
  const step = STEPS[index];
  const last = index === STEPS.length - 1;

  return (
    <div
      ref={barRef}
      role="region"
      aria-label="Walkthrough"
      className="no-print sticky top-0 z-50 bg-ink px-4 text-white"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 py-2.5">
        <div className="min-w-64 flex-1" aria-live="polite">
          <p className="text-sm">
            <span className="mr-2 text-xs font-semibold text-[#B9C4D1]">
              Step {index + 1} of {STEPS.length}
            </span>
            <span className="font-bold">{step.title}</span>
          </p>
          <p className="mt-0.5 text-sm text-[#DCE2EA]">{step.text}</p>
          {error && <p className="mt-1 text-sm text-[#F3B8B0]">{error}</p>}
          {done && !error && <p className="mt-1 text-xs text-[#B9C4D1]">Done.</p>}
        </div>
        <ol aria-hidden className="hidden items-center gap-1 md:flex">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <button
                tabIndex={-1}
                onClick={() => goTo(i)}
                title={s.title}
                className={`block size-2.5 rounded-full ${i === index ? "bg-white" : i < index ? "bg-white/60" : "bg-white/20"}`}
              />
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => goTo(index - 1)} disabled={index === 0 || busy} className={`${barButton} border-white/35 text-white`}>
            Back
          </button>
          {step.action && (
            <button onClick={act} disabled={busy} className={`${barButton} border-white bg-white text-ink`}>
              {busy ? "Working…" : step.action.label}
            </button>
          )}
          {!last && (
            <button
              onClick={() => goTo(index + 1)}
              disabled={busy}
              className={`${barButton} ${step.action ? "border-white/35 text-white" : "border-white bg-white text-ink"}`}
            >
              Next
            </button>
          )}
          <button onClick={begin} disabled={busy} className={quietLink}>
            {last ? "Start again" : "Restart"}
          </button>
          <button onClick={() => write(null)} className={quietLink}>
            Stop
          </button>
        </div>
      </div>
    </div>
  );
}
