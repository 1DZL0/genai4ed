import Link from "next/link";
import type { ReactNode } from "react";
import { Wordmark } from "@/components/app-header";

export const inputClass =
  "mt-1.5 block h-11 w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-base text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2";

/** One small sheet in the middle of the desk, for signing in. */
export function AuthLayout({
  role,
  title,
  lede,
  children,
}: {
  role: "teacher" | "student";
  title: string;
  lede: ReactNode;
  children: ReactNode;
}) {
  const other = role === "teacher" ? { href: "/join", label: "I'm a student" } : { href: "/login", label: "I'm a teacher" };
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
        <Wordmark />
        <Link
          href={other.href}
          className="text-sm font-semibold text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink"
        >
          {other.label}
        </Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pt-10 pb-16 sm:pt-20">
        <div className="w-full max-w-md rounded-[var(--radius-sheet)] border border-rule bg-sheet p-6 sm:p-8">
          <h1 className="font-serif text-xl font-semibold text-ink">{title}</h1>
          <p className="mt-1.5 mb-6 text-sm text-pencil">{lede}</p>
          {children}
        </div>
      </main>
    </div>
  );
}
