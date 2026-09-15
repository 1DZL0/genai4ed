"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { homeFor, useMe } from "@/lib/session";
import { Wordmark } from "@/components/app-header";
import { SubjectName } from "@/components/ui";

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
            Tell the class agent what to teach. It teaches every student, your way.
          </h1>
          <p className="mt-5 max-w-lg text-lg text-pencil">
            Describe the lesson and the rules in your own words. The agent turns them into an
            activity, runs it with each student as a conversation, and tells you who needs you and
            what the class is finding hard.
          </p>

          <div className="mt-9 grid max-w-lg gap-3 sm:grid-cols-2">
            <Door href="/login" title="I'm a teacher" line="Design and run a lesson" />
            <Door href="/join" title="I'm a student" line="Go to my lessons" />
          </div>

          <p className="mt-8 max-w-lg text-sm text-pencil">
            <span className="font-semibold text-amber">Internal prototype.</span> Not for use with
            real students until the school, data protection and ethics reviews are complete.
            Everyone here is fictional.
          </p>
        </div>

        <figure aria-label="Example: one lesson from teacher to student and back" className="hidden sm:block">
          <ol className="space-y-3">
            <Card label="The teacher tells the agent">
              &ldquo;Teach 8C about photosynthesis, 30 minutes. Hints are fine, but no final answer
              until they&apos;ve tried twice.&rdquo;
            </Card>
            <Card label="The agent teaches each student">
              <span className="block">
                <span className="text-pencil">Agent:</span> What does a plant need to make its own
                food?
              </span>
              <span className="block">
                <span className="text-pencil">7C-11:</span> sunlight and water?
              </span>
              <span className="block">
                <span className="text-pencil">Agent:</span> Good start. There&apos;s one more thing
                it takes from the air. What might that be?
              </span>
            </Card>
            <Card label="The teacher sees what matters">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <SubjectName subject="science" />
                <span className="font-semibold text-red-pen">1 needs you</span>
                <span className="text-pencil">· 4 students think plants get food from soil</span>
              </span>
            </Card>
          </ol>
        </figure>
      </main>
    </div>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <li className="rounded-[var(--radius-sheet)] border border-rule bg-sheet px-5 py-4 shadow-[0_1px_0_var(--rule),0_18px_40px_-28px_rgba(31,42,68,0.35)]">
      <p className="mb-1 text-xs font-bold text-pencil">{label}</p>
      <div className="space-y-1 text-sm text-ink">{children}</div>
    </li>
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
