"use client";

import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";
import { api } from "@/lib/api";
import { meKey, useMe } from "@/lib/session";
import { Wordmark } from "@/components/app-header";
import { SubjectName } from "@/components/ui";

export default function Home() {
  // Both roles are asked about, since one browser can hold both sign-ins.
  const teacher = useMe("teacher");
  const student = useMe("student");
  const [leaving, setLeaving] = useState(false);
  if (teacher === undefined || student === undefined) return null;

  async function signOutOfEverything() {
    setLeaving(true);
    try {
      await api.logout();
    } finally {
      await Promise.all(
        [meKey("teacher"), meKey("student"), meKey()].map((k) =>
          mutate(k, undefined, { revalidate: false }),
        ),
      );
      window.location.reload();
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Wordmark />
        {(teacher || student) && (
          <span className="ml-auto flex flex-wrap items-center gap-x-3 text-sm text-pencil">
            <span>
              Signed in as{" "}
              {[
                teacher && `Teacher ${teacher.pseudonym}`,
                student && `Student ${student.pseudonym}`,
              ]
                .filter(Boolean)
                .join(" and ")}
            </span>
            <button
              onClick={signOutOfEverything}
              disabled={leaving}
              className="font-semibold text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink"
            >
              {leaving ? "Signing out…" : "Sign out of everything"}
            </button>
          </span>
        )}
      </header>

      <main className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-4 pt-6 pb-16 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
        <div>
          <h1 className="max-w-xl font-serif text-3xl font-semibold text-ink sm:text-[3.05rem] sm:leading-[1.08]">
            Tell the class agent what to teach. It teaches every student, your
            way.
          </h1>
          <p className="mt-5 max-w-lg text-lg text-pencil">
            Describe the lesson and the rules in your own words. The agent turns
            them into an activity, runs it with each student as a conversation,
            and tells you who needs you and what the class is finding hard.
          </p>

          <div className="mt-9 grid max-w-lg gap-3 sm:grid-cols-2">
            <Door
              href={teacher ? "/teacher" : "/login"}
              title="I'm a teacher"
              line={
                teacher
                  ? `Carry on as ${teacher.pseudonym}`
                  : "Design and run a lesson"
              }
            />
            <Door
              href={student ? "/student" : "/join"}
              title="I'm a student"
              line={
                student
                  ? `Carry on as ${student.pseudonym}`
                  : "Go to my lessons"
              }
            />
          </div>

          <p className="mt-8 max-w-lg text-sm text-pencil">
            <span className="font-semibold text-amber">
              Internal prototype.
            </span>{" "}
            Not for use with real students until the school, data protection and
            ethics reviews are complete. Everyone here is fictional.
          </p>
        </div>

        <figure
          aria-label="Example: one lesson from teacher to student and back"
          className="hidden sm:block"
        >
          <ol className="space-y-3">
            <Card label="The teacher tells the agent">
              &ldquo;Teach 8C about photosynthesis, 30 minutes. Hints are fine,
              but no final answer until they&apos;ve tried twice.&rdquo;
            </Card>
            <Card label="The agent teaches each student">
              <span className="block">
                <span className="text-pencil">Agent:</span> What does a plant
                need to make its own food?
              </span>
              <span className="block">
                <span className="text-pencil">7C-11:</span> sunlight and water?
              </span>
              <span className="block">
                <span className="text-pencil">Agent:</span> Good start.
                There&apos;s one more thing it takes from the air. What might
                that be?
              </span>
            </Card>
            <Card label="The teacher sees what matters">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <SubjectName subject="science" />
                <span className="font-semibold text-red-pen">1 needs you</span>
                <span className="text-pencil">
                  · 4 students think plants get food from soil
                </span>
              </span>
            </Card>
          </ol>
        </figure>
      </main>
    </div>
  );
}

function Card({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <li className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4 shadow-[0_1px_0_var(--rule),0_18px_40px_-28px_rgba(31,42,68,0.35)]">
      <p className="mb-1 text-xs font-bold text-pencil">{label}</p>
      <div className="space-y-1 text-sm text-ink">{children}</div>
    </li>
  );
}

function Door({
  href,
  title,
  line,
}: {
  href: string;
  title: string;
  line: string;
}) {
  return (
    <Link
      href={href}
      className="group block rounded-[var(--radius-sheet)] border border-rule-strong bg-sheet px-5 py-4 transition-colors hover:border-ink"
    >
      <span>
        <span className="block text-lg font-bold text-ink">{title}</span>
        <span className="block text-sm text-pencil group-hover:text-ink">
          {line}
        </span>
      </span>
    </Link>
  );
}
