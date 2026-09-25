"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { mutate } from "swr";
import { api, type Me } from "@/lib/api";
import { meKey } from "@/lib/session";

const TEACHER_NAV = [
  { href: "/teacher", label: "Lessons" },
  { href: "/teacher/classes", label: "Classes" },
] as const;

export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="font-serif text-lg font-semibold tracking-tight text-ink">
      GenAI4ED
    </Link>
  );
}

export function AppHeader({ me }: { me: Me }) {
  const pathname = usePathname();
  const [leaving, setLeaving] = useState(false);

  async function signOut() {
    setLeaving(true);
    try {
      await api.logout(me.role);
    } finally {
      await mutate(meKey(me.role), undefined, { revalidate: false });
      await mutate(meKey(), undefined, { revalidate: false });
      // A full reload, not router.push, so nothing from the session stays cached on a shared computer.
      window.location.assign(me.role === "teacher" ? "/login" : "/join");
    }
  }

  return (
    <header className="no-print border-b border-rule bg-sheet">
      {/* On a phone the teacher's menu takes its own row under the wordmark; from `sm` up it sits beside it. */}
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 px-4 sm:h-14 sm:flex-nowrap sm:px-6">
        <div className="flex h-14 min-w-0 items-center gap-6 sm:h-auto">
          <Wordmark href={me.role === "teacher" ? "/teacher" : "/student"} />
        </div>
        {me.role === "teacher" && (
          <nav
            aria-label="Main"
            className="order-last -mx-2.5 flex h-11 w-full gap-1 sm:order-none sm:mx-0 sm:mr-auto sm:h-14 sm:w-auto"
          >
            {TEACHER_NAV.map(({ href, label }) => {
              const current = href === "/teacher" ? pathname === "/teacher" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={`flex items-center border-b-2 px-2.5 text-sm font-semibold whitespace-nowrap ${
                    current ? "border-ink text-ink" : "border-transparent text-pencil hover:text-ink"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        )}
        <div className="flex h-14 shrink-0 items-center gap-3 sm:h-auto">
          <span className="text-sm text-pencil">
            {me.role === "teacher" ? "Teacher" : "Student"}{" "}
            <span className="font-semibold text-ink">{me.email ?? me.pseudonym}</span>
          </span>
          {me.role === "teacher" && (
            <a
              href="/join"
              target="_blank"
              rel="noopener"
              className="text-sm font-semibold text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink"
            >
              Try it as a student
            </a>
          )}
          <button
            onClick={signOut}
            disabled={leaving}
            className="text-sm font-semibold text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink hover:decoration-ink"
          >
            {leaving ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </div>
    </header>
  );
}

export function PageTitle({ children, lede }: { children: React.ReactNode; lede?: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="font-serif text-2xl font-semibold text-ink">{children}</h1>
        {lede && <p className="mt-2 text-base text-pencil">{lede}</p>}
      </div>
    </div>
  );
}
