"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { homeFor, useMe } from "@/lib/session";
import { Wordmark } from "@/components/app-header";
import { LadderGauge, SubjectName, Tick } from "@/components/ui";

// A fictional register, drawn with the same parts the real console uses, so
// the front door shows what the platform actually looks like in a lesson.
const LADDER = [
  "attempt",
  "diagnostic_question",
  "conceptual_cue",
  "targeted_hint",
  "analogous_example",
  "partial_step",
];
const SAMPLE: { who: string; cells: (string | "solved" | null)[]; waiting?: boolean }[] = [
  { who: "7C-04", cells: ["solved", "solved", "conceptual_cue", null] },
  { who: "7C-11", cells: ["solved", "partial_step", null, null], waiting: true },
  { who: "7C-17", cells: ["solved", "solved", "solved", "diagnostic_question"] },
];

export default function Home() {
  const me = useMe();
  const router = useRouter();

  useEffect(() => {
    if (me) router.replace(homeFor(me.role));
  }, [me, router]);

  if (me !== null) return null;

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="mx-auto flex h-14 w-full max-w-6xl items-center px-4 sm:px-6">
        <Wordmark />
      </header>

      <main className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-4 pt-6 pb-16 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
        <div>
          <h1 className="max-w-xl font-serif text-3xl font-semibold text-ink sm:text-[3.05rem] sm:leading-[1.08]">
            A tutor for every student. The teacher decides how much it helps.
          </h1>
          <p className="mt-5 max-w-lg text-lg text-pencil">
            Each student works through the lesson with their own AI tutor. It gives one small step
            of help at a time, never more than the teacher allows, and tells the teacher when
            someone needs them.
          </p>

          <div className="mt-9 grid max-w-lg gap-3 sm:grid-cols-2">
            <Door href="/login" title="I'm a teacher" line="Run a lesson" />
            <Door href="/join" title="I'm a student" line="Go to my lessons" />
          </div>

          <p className="mt-8 max-w-lg text-sm text-pencil">
            <span className="font-semibold text-amber">Internal prototype.</span> Not for use with
            real students until the school, data protection and ethics reviews are complete.
            Everyone here is fictional.
          </p>
        </div>

        <figure aria-label="Example: a teacher's register during a lesson" className="hidden sm:block">
          <div className="rounded-[var(--radius-sheet)] border border-rule bg-sheet p-6 shadow-[0_1px_0_var(--rule),0_18px_40px_-24px_rgba(31,42,68,0.35)]">
            <div className="mb-5">
              <SubjectName subject="science" />
              <p className="font-serif text-lg font-semibold text-ink">Forces and motion</p>
              <p className="text-xs text-pencil">7C, 26 min left</p>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-pencil">
                  <th className="pb-2 font-semibold">Student</th>
                  {[1, 2, 3, 4].map((n) => (
                    <th key={n} className="pb-2 text-center font-semibold">
                      Q{n}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SAMPLE.map((row) => (
                  <tr key={row.who} className="border-t border-rule">
                    <td className="py-3 pr-2">
                      <span className="figures font-semibold text-ink">{row.who}</span>
                      {row.waiting && (
                        <span className="ml-2 text-xs font-bold text-red-pen">asked for you</span>
                      )}
                    </td>
                    {row.cells.map((cell, i) => (
                      <td key={i} className="py-3 text-center">
                        {cell === "solved" ? (
                          <Tick className="mx-auto size-5" />
                        ) : cell ? (
                          <LadderGauge rungs={LADDER} reached={cell} />
                        ) : (
                          <span aria-hidden className="text-rule-strong">
                            –
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <figcaption className="mt-3 text-sm text-pencil">
            The teacher&apos;s view: a tick for each answer that&apos;s right, and small steps
            showing how much help each student has had.
          </figcaption>
        </figure>
      </main>
    </div>
  );
}

function Door({ href, title, line }: { href: string; title: string; line: string }) {
  return (
    <Link
      href={href}
      className="group block rounded-[var(--radius-sheet)] border border-rule-strong bg-sheet px-5 py-4 transition-colors hover:border-ink"
    >
      <span>
        <span className="block text-lg font-bold text-ink">{title}</span>
        <span className="block text-sm text-pencil group-hover:text-ink">{line}</span>
      </span>
    </Link>
  );
}
