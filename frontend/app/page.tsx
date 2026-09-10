"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { setPseudonym } from "@/lib/identity";
import { Button, Panel } from "@/components/ui";

/**
 * Development entry point.
 *
 * In a classroom a student is handed their pseudonym and the teacher opens her
 * own console; nobody chooses a role from a menu. This page exists so the
 * prototype can be driven from one browser.
 */
const SEEDED = [
  { who: "teacher-01", role: "teacher" as const, note: "the class teacher" },
  { who: "10B-01", role: "student" as const, note: "has been struggling with item 1" },
  { who: "10B-02", role: "student" as const, note: "met a tutor response that was blocked" },
  { who: "10B-03", role: "student" as const, note: "has not started" },
];

export default function Home() {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  function enter(who: string, role: "teacher" | "student") {
    setBusy(who);
    setPseudonym(who);
    router.push(role === "teacher" ? "/teacher" : "/student");
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-semibold text-ink">GenAI4ED</h1>
      <p className="mt-1 text-sm text-muted">
        Teacher-governed personal AI tutors — internal prototype.
      </p>

      <div className="mt-6 rounded border border-sev2/30 bg-sev2/5 px-4 py-3 text-sm text-ink">
        <strong className="text-sev2">Not for student use.</strong> School and DPO review, ethics
        approval, and parental authorisation or student assent must all be settled first.
        The seeded lesson and the three students below are fictional.
      </div>

      <div className="mt-8">
        <Panel title="Continue as">
          <ul role="list" className="divide-y divide-border-subtle">
            {SEEDED.map(({ who, role, note }) => (
              <li key={who} className="flex items-center justify-between gap-4 py-3">
                <div>
                  <p className="font-mono text-sm text-ink">{who}</p>
                  <p className="text-xs text-muted">
                    {role} · {note}
                  </p>
                </div>
                <Button onClick={() => enter(who, role)} disabled={busy !== null}>
                  {busy === who ? "Opening…" : "Open"}
                </Button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <p className="mt-6 text-xs text-faint">
        Choosing a name here is not signing in. The backend trusts whatever pseudonym the browser
        sends, which is why this build must not meet a real class.
      </p>
    </main>
  );
}
