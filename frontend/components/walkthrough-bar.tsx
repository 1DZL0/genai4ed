"use client";

import { useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { api, ApiError, type Walkthrough } from "@/lib/api";

/**
 * The guided walkthrough: a bar across the top that steps through one English
 * lesson with a class of pretend students, who work through the real platform.
 * Demo mode only. Where the teacher is in it is kept in this browser.
 */

const KEY = "genai4ed-walkthrough";
type State = { run: Walkthrough; step: number };

let cached: string | null = null;
let cachedState: State | null = null;
function read(): State | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cached) {
    cached = raw;
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

type Step = {
  title: string;
  text: string;
  go?: (run: Walkthrough) => string;
  action?: { label: string; run: (w: Walkthrough) => Promise<string | void> };
};

const STEPS: Step[] = [
  {
    title: "The lesson plan",
    text: "The teacher approved this English plan: four phases, two writing tasks, a help limit of model sentences and a rubric out of 10. The AI never goes past what is written here.",
    go: () => "/teacher/contracts",
  },
  {
    title: "Today",
    text: "The lesson is booked for the class 9B Walkthrough: six pretend students, each behaving like a different kind of student.",
    go: () => "/teacher",
    action: {
      label: "Start the lesson",
      run: async (w) => {
        await api.startLesson(w.lesson_id);
        return `/teacher/${w.lesson_id}`;
      },
    },
  },
  {
    title: "Explanation: tutors off",
    text: "The class is listening to the teacher. Tutors are switched off on the server, so no student can use one, whatever their screen does.",
    go: (w) => `/teacher/${w.lesson_id}`,
    action: {
      label: "See a student's screen",
      run: async (w) => `/teacher/${w.lesson_id}/preview/${w.cast[3].student_id}`,
    },
  },
  {
    title: "Writing with tutors",
    text: "The teacher moves the class on. The pretend students start writing and ask their tutors. Watch the register fill in.",
    go: (w) => `/teacher/${w.lesson_id}`,
    action: {
      label: "Move on and let them write",
      run: async (w) => {
        await api.changePhase(w.lesson_id, w.writing_phase);
        await api.simulate(w.lesson_id, "start_writing");
        return `/teacher/${w.lesson_id}`;
      },
    },
  },
  {
    title: "Help, one step at a time",
    text: "Look at a student who said they were stuck before writing: the tutor asked them to have a go first, then gave a hint once they had written something.",
    go: (w) => `/teacher/${w.lesson_id}/preview/${w.cast[1].student_id}`,
  },
  {
    title: "Someone needs you",
    text: "One student keeps asking without writing anything, and another asks for the teacher. Both appear under Needs you. Click See their work.",
    go: (w) => `/teacher/${w.lesson_id}`,
    action: {
      label: "Make it happen",
      run: async (w) => {
        await api.simulate(w.lesson_id, "get_stuck");
        return `/teacher/${w.lesson_id}`;
      },
    },
  },
  {
    title: "Handing in",
    text: "Five students hand in. The tutor suggests a score for each against the rubric, but students see nothing yet. One student is still writing.",
    go: (w) => `/teacher/${w.lesson_id}`,
    action: {
      label: "Hand in their work",
      run: async (w) => {
        await api.simulate(w.lesson_id, "hand_in");
        return `/teacher/${w.lesson_id}`;
      },
    },
  },
  {
    title: "The teacher decides the score",
    text: "Under Scores to confirm, open a student's paragraph, read the tutor's reasons, change any points, add a comment and press Confirm score.",
    go: (w) => `/teacher/${w.lesson_id}`,
  },
  {
    title: "What the student sees",
    text: "The first student's screen. Once their score is confirmed it appears here with what went well and your comment; until then it says the teacher will mark it.",
    go: (w) => `/teacher/${w.lesson_id}/preview/${w.cast[0].student_id}`,
  },
  {
    title: "End and review",
    text: "End the lesson, then go through each student's paragraph, help and scores afterwards.",
    go: (w) => `/teacher/${w.lesson_id}`,
    action: {
      label: "End lesson and review",
      run: async (w) => {
        await api.setSessionState(w.lesson_id, "closed");
        return `/teacher/lessons/${w.lesson_id}/review`;
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
  const [log, setLog] = useState<string | null>(null);

  if (!config?.demo_sign_in) return null;

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.beginWalkthrough();
      write({ run, step: 0 });
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
    setLog(null);
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
      const target = await action.run(state.run);
      await mutate(() => true);
      if (target) router.push(target);
      setLog("Done.");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const barButton =
    "h-9 rounded-[var(--radius-control)] border px-3.5 text-sm font-bold whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-40";

  if (!state) {
    return (
      <div className="no-print bg-ink px-4 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 py-2 text-sm">
          <span className="flex-1">
            Showing someone the platform? Walk through a whole English lesson with pretend students.
          </span>
          {error && <span className="text-[#F3B8B0]">{error}</span>}
          <button onClick={begin} disabled={busy} className={`${barButton} border-white bg-white text-ink`}>
            {busy ? "Setting up…" : "Start the walkthrough"}
          </button>
        </div>
      </div>
    );
  }

  const step = STEPS[Math.min(state.step, STEPS.length - 1)];
  const last = state.step >= STEPS.length - 1;

  return (
    <div role="region" aria-label="Walkthrough" className="no-print sticky top-0 z-50 bg-ink px-4 text-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 py-2.5">
        <div className="min-w-64 flex-1" aria-live="polite">
          <p className="text-sm">
            <span className="mr-2 text-xs font-semibold text-[#B9C4D1]">
              Step {state.step + 1} of {STEPS.length}
            </span>
            <span className="font-bold">{step.title}</span>
          </p>
          <p className="mt-0.5 text-sm text-[#DCE2EA]">{step.text}</p>
          {error && <p className="mt-1 text-sm text-[#F3B8B0]">{error}</p>}
          {log && !error && <p className="mt-1 text-xs text-[#B9C4D1]">{log}</p>}
        </div>
        <ol aria-hidden className="hidden items-center gap-1 md:flex">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <button
                tabIndex={-1}
                onClick={() => goTo(i)}
                title={s.title}
                className={`block size-2.5 rounded-full ${i === state.step ? "bg-white" : i < state.step ? "bg-white/60" : "bg-white/20"}`}
              />
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => goTo(state.step - 1)}
            disabled={state.step === 0 || busy}
            className={`${barButton} border-white/35 text-white`}
          >
            Back
          </button>
          {step.action && (
            <button onClick={act} disabled={busy} className={`${barButton} border-white bg-white text-ink`}>
              {busy ? "Working…" : step.action.label}
            </button>
          )}
          {last ? (
            <button onClick={begin} disabled={busy} className={`${barButton} border-white/35 text-white`}>
              Start again
            </button>
          ) : (
            <button
              onClick={() => goTo(state.step + 1)}
              disabled={busy}
              className={`${barButton} ${step.action ? "border-white/35 text-white" : "border-white bg-white text-ink"}`}
            >
              Next
            </button>
          )}
          {!last && (
            <button
              onClick={begin}
              disabled={busy}
              className="h-9 px-2 text-sm text-[#B9C4D1] underline underline-offset-4 hover:text-white"
            >
              Restart
            </button>
          )}
          <button
            onClick={() => write(null)}
            className="h-9 px-2 text-sm text-[#B9C4D1] underline underline-offset-4 hover:text-white"
          >
            Stop
          </button>
        </div>
      </div>
    </div>
  );
}
