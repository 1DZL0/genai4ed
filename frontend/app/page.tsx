"use client";

import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";
import { api } from "@/lib/api";
import { meKey, useMe } from "@/lib/session";
import { Wordmark } from "@/components/app-header";
import { Framework } from "@/components/framework";

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

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-8 px-4 pt-8 pb-16 text-center sm:px-6">
        <h1 className="max-w-3xl font-serif text-3xl font-semibold text-ink sm:text-[2.75rem] sm:leading-[1.1]">
          One class agent between a teacher and their students.
        </h1>

        <Framework />

        <div className="grid w-full max-w-lg gap-3 sm:grid-cols-2">
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
              student ? `Carry on as ${student.pseudonym}` : "Go to my lessons"
            }
          />
        </div>

        <p className="max-w-lg text-sm text-pencil">
          <span className="font-semibold text-amber">Internal prototype.</span>{" "}
          Not for use with real students until the school, data protection and
          ethics reviews are complete. Everyone here is fictional.
        </p>
      </main>
    </div>
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
