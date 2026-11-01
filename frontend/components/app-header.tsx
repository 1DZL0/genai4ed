"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { mutate } from "swr";
import { api, type Me } from "@/lib/api";
import { fullSignOutUrl, meKey } from "@/lib/session";

type Tab = { href: string; label: string; icon: keyof typeof ICONS };

const TEACHER_NAV: Tab[] = [
  { href: "/teacher", label: "Lessons", icon: "lessons" },
  { href: "/teacher/classes", label: "Classes", icon: "classes" },
  { href: "/research", label: "Research", icon: "research" },
];
// The research view holds every student's words, so it is never offered to a student.
const STUDENT_NAV: Tab[] = [{ href: "/student", label: "Lessons", icon: "lessons" }];
/** The teacher's rail: the three pages, and the student sign-in in a new tab. */
const RAIL: Tab[] = [
  ...TEACHER_NAV,
  { href: "/join", label: "Student side", icon: "student" },
];

// Small line icons, drawn on a 20px grid so they sit on the text baseline.
const ICONS = {
  lessons:
    "M4 4.5h5a2 2 0 0 1 2 2V16a1.5 1.5 0 0 0-1.5-1.5H4zM16 4.5h-5a2 2 0 0 0-2 2V16a1.5 1.5 0 0 1 1.5-1.5H16z",
  classes:
    "M7 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM2.5 16c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5M13.5 9a2.25 2.25 0 1 0 0-4.5M14 11.5c2 .3 3.5 2 3.5 4.5",
  research: "M4 16V9M8.5 16V4M13 16v-5M17 16H3",
  student:
    "M3 5.5A1.5 1.5 0 0 1 4.5 4h11A1.5 1.5 0 0 1 17 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 12.5zM7 17h6",
} as const;

function Icon({
  name,
  className = "size-[18px]",
}: {
  name: keyof typeof ICONS;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      className={`shrink-0 fill-none stroke-current ${className}`}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={ICONS[name]} />
    </svg>
  );
}

export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link
      href={href}
      className="font-serif text-lg font-semibold tracking-tight text-ink"
    >
      GenAI4ED
    </Link>
  );
}

/** Who is signed in, and the ways out. `compact` is the rail's: initials only, menu to the side. */
function AccountMenu({ me, compact = false }: { me: Me; compact?: boolean }) {
  const [leaving, setLeaving] = useState(false);
  const teacher = me.role === "teacher";
  const name = me.email ?? me.pseudonym;

  // `all` ends both sign-ins, the teacher's and the student's, in every tab of this browser.
  async function signOut(all = false) {
    setLeaving(true);
    try {
      await api.logout(all ? undefined : me.role);
    } finally {
      await mutate(meKey(me.role), undefined, { revalidate: false });
      await mutate(meKey(), undefined, { revalidate: false });
      // A full reload, not router.push, so nothing from the session stays cached on a shared computer.
      window.location.assign(
        all ? fullSignOutUrl() : teacher ? "/login" : "/join",
      );
    }
  }

  return (
    <details className="group relative">
      <summary
        className={`flex cursor-pointer list-none items-center gap-2 hover:bg-sunken [&::-webkit-details-marker]:hidden ${
          compact
            ? "flex-col gap-1 rounded-[10px] px-1 py-1.5"
            : "rounded-full py-1 pr-2 pl-1"
        }`}
      >
        <span
          aria-hidden="true"
          className="flex size-8 items-center justify-center rounded-full bg-ink text-xs font-bold text-white"
        >
          {initials(name)}
        </span>
        {compact && (
          <span className="max-w-20 truncate text-xs font-semibold text-pencil">
            {name}
          </span>
        )}
        {!compact && (
          <>
            <span className="hidden text-sm font-semibold text-ink sm:inline">
              {name}
            </span>
            <svg
              viewBox="0 0 20 20"
              aria-hidden="true"
              className="size-4 fill-none stroke-current text-pencil transition-transform group-open:rotate-180"
              strokeWidth={1.8}
            >
              <path d="M6 8l4 4 4-4" />
            </svg>
          </>
        )}
        <span className="sr-only">Account and sign out</span>
      </summary>
      <div
        className={`absolute z-20 w-64 rounded-[var(--radius-sheet)] border border-rule bg-sheet p-2 shadow-lg ${
          compact
            ? "right-0 mt-2 lg:right-auto lg:bottom-0 lg:left-full lg:mt-0 lg:ml-2"
            : "right-0 mt-2"
        }`}
      >
        <p className="px-3 pt-2 pb-3 text-sm text-pencil">
          Signed in as {teacher ? "teacher" : "student"}{" "}
          <span className="font-semibold text-ink">{name}</span>
        </p>
        <button
          onClick={() => signOut()}
          disabled={leaving}
          className="w-full rounded-[var(--radius-control)] px-3 py-2 text-left text-sm font-semibold text-ink hover:bg-sunken"
        >
          {leaving ? "Signing out…" : "Sign out"}
        </button>
        <button
          onClick={() => signOut(true)}
          disabled={leaving}
          className="w-full rounded-[var(--radius-control)] px-3 py-2 text-left text-sm text-ink hover:bg-sunken"
        >
          Sign out of everything
          <span className="block text-xs text-pencil">
            The teacher and the student, in every tab of this browser
          </span>
        </button>
      </div>
    </details>
  );
}

/** The teacher's way around: four buttons down the left with the account at the bottom. On a phone it lies along the top. */
export function Rail({ me }: { me: Me }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="no-print flex shrink-0 items-stretch gap-1 border-b border-rule bg-sheet px-2 py-1.5 lg:w-24 lg:flex-col lg:border-r lg:border-b-0 lg:py-4"
    >
      {RAIL.map(({ href, label, icon }) => {
        const outside = href === "/join";
        const current =
          !outside &&
          (href === "/teacher" ? pathname === href : pathname.startsWith(href));
        const look = `flex flex-1 flex-col items-center gap-1 rounded-[10px] px-1 py-2 text-center text-xs font-semibold lg:flex-none lg:py-2.5 lg:text-[13px] ${
          current
            ? "bg-sunken text-ink"
            : "text-pencil hover:bg-sunken/60 hover:text-ink"
        }`;
        return outside ? (
          <a
            key={href}
            // Names this teacher, so a demo student made there joins their class.
            href={`${href}?teacher=${encodeURIComponent(me.pseudonym)}`}
            target="_blank"
            rel="noopener"
            title="Opens the student sign-in in a new tab, so you can be teacher and student at once"
            className={look}
          >
            <Icon name={icon} className="size-[22px]" />
            {label}
          </a>
        ) : (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={look}
          >
            <Icon name={icon} className="size-[22px]" />
            {label}
          </Link>
        );
      })}
      <div className="flex items-center justify-center lg:mt-auto">
        <AccountMenu me={me} compact />
      </div>
    </nav>
  );
}

/** The page frame. A teacher gets the rail down the left and the page scrolls beside it; a student gets the header across the top. */
export function Shell({
  me,
  children,
}: {
  me: Me | null | undefined;
  children: React.ReactNode;
}) {
  if (!me) return <>{children}</>;
  if (me.role !== "teacher")
    return (
      <>
        <AppHeader me={me} />
        {children}
      </>
    );
  return (
    <div className="flex h-dvh flex-col lg:flex-row">
      <Rail me={me} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

export function AppHeader({ me }: { me: Me }) {
  const pathname = usePathname();
  const teacher = me.role === "teacher";
  const other = teacher ? "student" : "teacher";

  return (
    <header className="no-print border-b border-rule bg-sheet">
      {/* Phone: wordmark and account on one row, the tabs full width under them. */}
      <div className="flex w-full flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 sm:flex-nowrap sm:px-6">
        <Wordmark href={teacher ? "/teacher" : "/student"} />

        <nav
          aria-label="Main"
          className="order-last flex w-full gap-1 rounded-full bg-sunken p-1 sm:order-none sm:w-auto"
        >
          {(teacher ? TEACHER_NAV : STUDENT_NAV).map(
            ({ href, label, icon }) => {
              const current =
                href === "/teacher" || href === "/student"
                  ? pathname === href
                  : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-full px-4 py-2 text-[15px] font-semibold whitespace-nowrap transition-colors sm:flex-none ${
                    current
                      ? "bg-sheet text-ink shadow-[0_1px_2px_rgb(15_23_42/0.12)] ring-1 ring-rule"
                      : "text-pencil hover:bg-sheet/60 hover:text-ink"
                  }`}
                >
                  <Icon name={icon} />
                  {label}
                </Link>
              );
            },
          )}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {/* A teacher trying the platform can open a pupil's view beside their own. A pupil
              is shown nothing of the kind: their screen is the lesson. */}
          {teacher && (
            <a
              href={`/join?teacher=${encodeURIComponent(me.pseudonym)}`}
              target="_blank"
              rel="noopener"
              title={`Opens the ${other} sign-in in a new tab, so you can be teacher and student at once`}
              className="flex items-center gap-2 rounded-full border border-rule-strong px-3.5 py-2 text-sm font-semibold text-ink hover:border-ink"
            >
              <Icon name="student" />
              <span className="hidden sm:inline">Sign in as a {other}</span>
              <span className="sr-only sm:hidden">Sign in as a {other}</span>
            </a>
          )}

          <AccountMenu me={me} />
        </div>
      </div>
    </header>
  );
}

/** "teacher-3" becomes T3, "Ms Kay" becomes MK. */
function initials(name: string): string {
  const parts = name.split(/[\s\-_.@]+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

export function PageTitle({
  children,
  lede,
}: {
  children: React.ReactNode;
  lede?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="font-serif text-2xl font-semibold text-ink">
          {children}
        </h1>
        {lede && <p className="mt-2 text-base text-pencil">{lede}</p>}
      </div>
    </div>
  );
}
