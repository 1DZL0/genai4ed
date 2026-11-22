"use client";

import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";
import { api } from "@/lib/api";
import { fullSignOutUrl, meKey, useMe } from "@/lib/session";
import { Wordmark } from "@/components/app-header";
import { useDemoSignIn } from "@/components/demo-sign-in";
import { Framework } from "@/components/framework";

export default function Home() {
  // Both roles are asked about, since one browser can hold both sign-ins.
  const teacher = useMe("teacher");
  const student = useMe("student");
  // Demo sign-in is on for Athens; turning it off removes the demo line and the demo wording.
  const demo = useDemoSignIn() === true;
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
      window.location.assign(fullSignOutUrl());
    }
  }

  /** One role out, to the sign-in for that role, so someone else can take that seat. */
  async function signOut(role: "teacher" | "student") {
    setLeaving(true);
    try {
      await api.logout(role);
    } finally {
      await mutate(meKey(role), undefined, { revalidate: false });
      await mutate(meKey(), undefined, { revalidate: false });
      window.location.assign(role === "teacher" ? "/login" : "/join");
    }
  }

  const signedIn = [
    teacher && `Teacher ${teacher.pseudonym}`,
    student && `Student ${student.pseudonym}`,
  ].filter(Boolean);

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b border-rule bg-sheet">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 sm:px-6">
          <span className="flex items-center gap-2.5">
            <AppIcon />
            <Wordmark />
          </span>
          <nav
            aria-label="Main"
            className="ml-auto flex items-center gap-4 text-[15px] font-bold sm:gap-6"
          >
            <a
              href="#how"
              className="hidden text-pencil hover:text-ink sm:inline"
            >
              How it works
            </a>
            {!teacher && (
              <Link href="/login" className="text-ink hover:text-accent">
                Teacher<span className="hidden sm:inline"> sign in</span>
              </Link>
            )}
            {!student && (
              <Link
                href="/join"
                className="rounded-full bg-ink px-4 py-2 text-white hover:bg-ink-hover"
              >
                Join a lesson
              </Link>
            )}
          </nav>
          {signedIn.length > 0 && (
            <p className="flex w-full flex-wrap justify-end gap-x-3 text-sm text-pencil">
              <span>Signed in as {signedIn.join(" and ")}</span>
              <button
                onClick={signOutOfEverything}
                disabled={leaving}
                className="font-semibold underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink"
              >
                {leaving ? "Signing out…" : "Sign out of everything"}
              </button>
            </p>
          )}
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        <section className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pt-12 pb-10 text-center sm:px-6 sm:pt-16">
          <p
            aria-hidden="true"
            className="font-serif text-[4.5rem] leading-[0.9] font-semibold tracking-[0.01em] text-ink sm:text-[6.5rem]"
          >
            PACT<span className="text-accent">.</span>
          </p>
          <p className="mt-2 text-base font-bold tracking-[0.02em] text-pencil sm:text-lg">
            <Initial>P</Initial>ersonal <Initial>A</Initial>gent for{" "}
            <Initial>C</Initial>lass <Initial>T</Initial>eaching
          </p>
          <h1 className="mt-8 max-w-[20ch] font-serif text-[1.6rem] leading-[1.15] font-semibold text-balance text-ink sm:text-[2.1rem]">
            A personal tutor for every student, with the teacher in charge.
          </h1>
          <p className="mt-4 max-w-[56ch] text-base text-balance text-pencil sm:text-lg">
            The teacher plans the lesson with an AI agent. Each student then
            works through it with their own tutor, inside the rules the teacher
            approved.
          </p>
        </section>

        <section className="mx-auto grid w-full max-w-4xl gap-5 px-4 sm:grid-cols-2 sm:px-6">
          <Door
            tone="teacher"
            eyebrow="For teachers"
            title="Plan and run a lesson"
            lines={[
              "Describe the lesson in your own words. The agent drafts it for you.",
              "Nothing reaches your students until you approve it.",
              "During the lesson, see who is stuck and step in.",
              "Afterwards, confirm how each student did.",
            ]}
            href={teacher ? "/teacher" : "/login"}
            action={
              teacher
                ? `Carry on as ${teacher.pseudonym}`
                : "Sign in as a teacher"
            }
            other={
              teacher && (
                <button
                  onClick={() => signOut("teacher")}
                  disabled={leaving}
                  className="underline decoration-rule-strong underline-offset-4 hover:text-ink"
                >
                  Not {teacher.pseudonym}? Sign in as another teacher
                </button>
              )
            }
          />
          <Door
            tone="student"
            eyebrow="For students"
            title="Learn with your own tutor"
            lines={[
              // The demo student sign-in has no code: a student picks their teacher's class.
              demo
                ? "Pick your teacher's class to join."
                : "Type the code your teacher gave you.",
              "Your tutor takes you through your teacher's lesson, one step at a time.",
              "It remembers what you found hard last time.",
              'Press "Ask my teacher" whenever you want a person.',
            ]}
            href={student ? "/student" : "/join"}
            action={
              student
                ? `Carry on as ${student.pseudonym}`
                : demo
                  ? "Join a lesson"
                  : "Join with a code"
            }
            other={
              student && (
                <button
                  onClick={() => signOut("student")}
                  disabled={leaving}
                  className="underline decoration-rule-strong underline-offset-4 hover:text-ink"
                >
                  Not {student.pseudonym}? Sign in as another student
                </button>
              )
            }
          />
        </section>

        {demo && !teacher && (
          <p className="mt-6 px-4 text-center text-[15px] text-pencil">
            Just looking?{" "}
            <Link href="/login" className="font-bold text-accent hover:underline">
              Try PACT as a demo teacher →
            </Link>
          </p>
        )}

        <section
          id="how"
          className="mt-12 scroll-mt-4 border-y border-rule bg-sheet px-4 py-12 sm:px-6"
        >
          <div className="mx-auto flex max-w-4xl flex-col items-center gap-6">
            <div className="text-center">
              <h2 className="font-serif text-[1.7rem] font-semibold text-ink">
                How it works
              </h2>
              <p className="mt-1 text-pencil">
                One class agent sits between the teacher and the students.
              </p>
            </div>
            <Framework />
            <ol className="grid w-full gap-4 sm:grid-cols-3">
              <Step
                n={1}
                when="Before"
                title="The lesson is planned"
                text="The teacher describes it. The agent asks for the aim, the age and the length, then drafts the steps and the help rules."
                decides="The teacher approves it"
              />
              <Step
                n={2}
                when="During"
                title="Every student gets a tutor"
                text="Each tutor follows the approved lesson. Every reply is checked before the student sees it."
                decides="The teacher answers alerts"
              />
              <Step
                n={3}
                when="After"
                title="The lesson is reviewed"
                text="The agent suggests an outcome for each student. Each tutor remembers it for that student's next lesson."
                decides="The teacher confirms them"
              />
            </ol>
          </div>
        </section>

        <section className="mx-auto w-full max-w-4xl px-4 py-12 sm:px-6">
          <h2 className="text-center font-serif text-[1.7rem] font-semibold text-ink">
            Safe by design
          </h2>
          <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Fact icon="person" title="No real names">
              Students use a code name. PACT never asks for their name.
            </Fact>
            <Fact icon="tick" title="Every reply checked">
              Each answer from the tutor is checked before the student sees it.
            </Fact>
            <Fact icon="sheet" title="The teacher approves">
              Nothing reaches students until the teacher has approved the
              lesson.
            </Fact>
            <Fact icon="store" title="Our own database">
              Everything is kept in the project&apos;s own database.
            </Fact>
          </ul>
        </section>

        <section className="bg-ink px-4 py-9 text-white sm:px-6">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-x-8 gap-y-4">
            <p
              aria-hidden="true"
              className="font-serif text-[3.6rem] leading-none font-semibold tracking-[0.01em]"
            >
              PACT<span className="text-[#c9b8f2]">.</span>
            </p>
            <div className="max-w-[34ch] text-[#e8e4f2]">
              <p className="font-bold text-white">
                Personal Agent for Class Teaching
              </p>
              <p>
                The full stop means agreed: the teacher sets the rules, and the
                agent keeps them.
              </p>
              <p className="mt-2 text-sm">
                A research project of{" "}
                <span className="font-bold text-white">
                  The Cyprus Institute
                </span>
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

/** The site icon, drawn small beside the wordmark: "P." on the purple tile. */
function AppIcon() {
  return (
    <span
      aria-hidden="true"
      className="inline-grid size-[34px] place-items-center rounded-[9px] bg-accent pt-0.5 font-serif text-[1.35rem] leading-none font-extrabold text-white"
    >
      <span>
        P
        <span className="ml-[0.03em] inline-block size-[0.2em] rounded-full bg-[#e4daff]" />
      </span>
    </span>
  );
}

function Initial({ children }: { children: string }) {
  return <span className="text-ink">{children}</span>;
}

const TONES = {
  teacher: {
    dot: "bg-accent",
    badge: "bg-accent/10 text-accent",
    button: "bg-accent text-white hover:bg-accent-hover",
  },
  student: {
    dot: "bg-tick",
    badge: "bg-tick-wash text-tick",
    button:
      "border-[1.5px] border-rule-strong bg-sheet text-ink hover:border-ink",
  },
} as const;

function Door({
  tone,
  eyebrow,
  title,
  lines,
  href,
  action,
  other,
}: {
  tone: keyof typeof TONES;
  eyebrow: string;
  title: string;
  lines: string[];
  href: string;
  action: string;
  other?: React.ReactNode;
}) {
  const look = TONES[tone];
  return (
    <article className="flex flex-col gap-4 rounded-[18px] border border-rule-strong bg-sheet p-6">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className={`flex size-10 shrink-0 items-center justify-center rounded-full ${look.badge}`}
        >
          <svg viewBox="0 0 20 20" className="size-5 fill-current">
            <circle cx="10" cy="7" r="3.5" />
            <path d="M3.5 17c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5z" />
          </svg>
        </span>
        <div>
          <p className="text-xs font-extrabold tracking-[0.1em] text-pencil uppercase">
            {eyebrow}
          </p>
          <h2 className="font-serif text-[1.4rem] leading-tight font-semibold text-ink">
            {title}
          </h2>
        </div>
      </div>
      <ul className="flex flex-1 flex-col gap-2 text-[15px] text-ink">
        {lines.map((line) => (
          <li key={line} className="flex gap-3">
            <span
              aria-hidden="true"
              className={`mt-[0.55em] size-2 shrink-0 rounded-full ${look.dot}`}
            />
            {line}
          </li>
        ))}
      </ul>
      <div className="flex flex-col items-start gap-2">
        <Link
          href={href}
          className={`rounded-full px-5 py-2.5 text-[15px] font-extrabold ${look.button}`}
        >
          {action} →
        </Link>
        {other && <p className="text-sm text-pencil">{other}</p>}
      </div>
    </article>
  );
}

function Step({
  n,
  when,
  title,
  text,
  decides,
}: {
  n: number;
  when: string;
  title: string;
  text: string;
  decides: string;
}) {
  return (
    <li className="flex flex-col rounded-[14px] border border-rule bg-paper p-5">
      <p className="mb-2 flex items-center gap-2.5">
        <span className="flex size-7 items-center justify-center rounded-full bg-ink text-sm font-bold text-white">
          {n}
        </span>
        <span className="text-xs font-extrabold tracking-[0.1em] text-pencil uppercase">
          {when}
        </span>
      </p>
      <h3 className="font-serif text-lg font-semibold text-ink">{title}</h3>
      <p className="mt-1 flex-1 text-sm text-pencil">{text}</p>
      <p className="mt-3 rounded-lg bg-accent/10 px-3 py-1.5 text-sm font-bold text-accent">
        {decides}
      </p>
    </li>
  );
}

// Small line icons for the safety facts, drawn on a 20px grid like the header's.
const FACT_ICONS = {
  person: "M10 9.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM4.5 16.5c.8-3.2 3-4.8 5.5-4.8s4.7 1.6 5.5 4.8",
  tick: "M5 10.5l3.2 3.2L15 6.5",
  sheet: "M6 3.5h8a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1zM8 8h4M8 11h3",
  store:
    "M10 7.2c3 0 5.3-1 5.3-2.2S13 2.8 10 2.8 4.7 3.8 4.7 5 7 7.2 10 7.2zM4.7 5v10c0 1.2 2.3 2.2 5.3 2.2s5.3-1 5.3-2.2V5",
} as const;

function Fact({
  icon,
  title,
  children,
}: {
  icon: keyof typeof FACT_ICONS;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex flex-col gap-1.5 rounded-[14px] border border-rule bg-sheet p-4">
      <span
        aria-hidden="true"
        className="flex size-8 items-center justify-center rounded-full bg-accent/10 text-accent"
      >
        <svg
          viewBox="0 0 20 20"
          className="size-[18px] fill-none stroke-current"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d={FACT_ICONS[icon]} />
        </svg>
      </span>
      <h3 className="font-serif text-[1.02rem] font-semibold text-ink">
        {title}
      </h3>
      <p className="text-sm text-pencil">{children}</p>
    </li>
  );
}
