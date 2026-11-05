"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui";

/* The three screens that take over the pupil's page: paused by the teacher, time up while
   the teacher decides, and the lesson ended. Each is one calm sheet over a grey wash, with
   one line a pupil can read at a glance. */

function Screen({
  tone,
  title,
  children,
  action,
}: {
  tone: "grey" | "amber" | "green";
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  const wash =
    tone === "amber" ? "bg-amber-wash/95" : tone === "green" ? "bg-tick-wash/95" : "bg-sunken/95";
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="lesson-screen-title"
      className={`fixed inset-0 z-40 flex items-center justify-center px-6 ${wash} backdrop-blur-[2px]`}
    >
      <div className="w-full max-w-md rounded-[var(--radius-sheet)] border border-rule bg-sheet px-7 py-8 text-center shadow-lg">
        <h2 id="lesson-screen-title" className="font-serif text-3xl font-semibold text-ink">
          {title}
        </h2>
        <div className="mt-3 text-base text-pencil">{children}</div>
        {action && <div className="mt-6">{action}</div>}
      </div>
    </div>
  );
}

export function PausedScreen() {
  return (
    <Screen tone="grey" title="Paused">
      Your teacher has paused the lesson. It will carry on from here when they start it again.
    </Screen>
  );
}

export function TimeUpScreen() {
  return (
    <Screen tone="amber" title="Time&apos;s up">
      Your work is saved. Your teacher will end the lesson or add some more time.
    </Screen>
  );
}

export function EndedScreen({ onLookBack }: { onLookBack: () => void }) {
  return (
    <Screen
      tone="green"
      title="Lesson ended"
      action={<Button onClick={onLookBack}>See how it went</Button>}
    >
      Your teacher ended the lesson. Everything you wrote is saved.
    </Screen>
  );
}
