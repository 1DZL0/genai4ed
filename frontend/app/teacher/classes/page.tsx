"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR, { mutate as refresh } from "swr";
import {
  api,
  ApiError,
  type ClassOut,
  type ClassProgress,
  type ProgressCell,
  type RosterEntry,
} from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { PageTitle, Shell } from "@/components/app-header";
import { classColour } from "@/components/cards/parts";
import { Button, Empty, ErrorNote, Notice, Skeleton } from "@/components/ui";

/* ---------- small pieces ---------- */

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className={`size-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

function Plus() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className="size-3.5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <path d="M8 3.5v9M3.5 8h9" />
    </svg>
  );
}

/** A round button. With `expanded` it opens and closes a part of the card, and says so. */
function Pill({
  tone = "quiet",
  expanded,
  controls,
  className = "",
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "quiet" | "primary";
  expanded?: boolean;
  controls?: string;
}) {
  const look =
    tone === "primary"
      ? "border-ink bg-ink text-white hover:bg-ink-hover disabled:border-faint disabled:bg-faint"
      : expanded
        ? "border-ink bg-sunken text-ink"
        : "border-rule-strong bg-sheet text-ink hover:border-ink disabled:text-faint disabled:hover:border-rule-strong";
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-controls={expanded ? controls : undefined}
      {...props}
      className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${look} ${className}`}
    >
      {children}
      {expanded !== undefined && <Chevron open={expanded} />}
    </button>
  );
}

/** A soft round label: a colour and always its word. */
function Tag({ tone, children }: { tone: "tick" | "amber" | "progress"; children: React.ReactNode }) {
  const look = {
    tick: "bg-tick-wash text-tick",
    amber: "bg-amber-wash text-amber",
    progress: "bg-progress-wash text-progress",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${look}`}
    >
      {children}
    </span>
  );
}

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "19 Oct", with the year only when it is not this year. */
function shortDate(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(d.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" }),
  });
}

const field =
  "h-11 rounded-full border border-rule-strong bg-sheet px-4 text-sm text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none";

const HOW_IT_WORKS: [string, string][] = [
  ["Make a class", "Give it a name and say how many students are in it."],
  ["Give out the codes", "Each student gets a numbered name and a code to sign in with."],
  ["Start a lesson", "On Lessons, open a lesson and start it with the class."],
];

/* ---------- the page ---------- */

export default function Classes() {
  const me = useSignedIn("teacher");
  const { data: classes, error, mutate } = useSWR<ClassOut[]>(me ? "classes" : null, api.classes);
  const [making, setMaking] = useState(false);

  if (!me) return null;

  const none = classes?.length === 0;

  return (
    <Shell me={me}>
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle lede="A class is a group of students you teach together. Each student signs in with a short code from you, with no name or password, and a lesson you start opens for the whole class at once. The platform never learns who your students are.">
          Classes
        </PageTitle>

        {none && (
          <ol className="mb-6 grid gap-3 sm:grid-cols-3" aria-label="How it works">
            {HOW_IT_WORKS.map(([title, body], i) => (
              <li
                key={title}
                className="flex gap-3 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3"
              >
                <span
                  aria-hidden="true"
                  className="figures grid size-8 shrink-0 place-items-center rounded-full bg-sunken text-sm font-bold text-ink"
                >
                  {i + 1}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-ink">{title}</span>
                  <span className="block text-sm text-pencil">{body}</span>
                </span>
              </li>
            ))}
          </ol>
        )}

        {(none || making) && (
          <MakeClass
            first={none}
            onMade={async () => {
              setMaking(false);
              await mutate();
            }}
            onCancel={none ? undefined : () => setMaking(false)}
          />
        )}

        {classes && classes.length > 0 && !making && (
          <div className="no-print mb-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-pencil">
              You have {classes.length === 1 ? "1 class" : `${classes.length} classes`}.
            </p>
            <Pill tone="primary" onClick={() => setMaking(true)}>
              <Plus />
              Make a class
            </Pill>
          </div>
        )}

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !classes && <Skeleton label="Loading your classes" rows={2} />}
        <div className="space-y-6">
          {classes?.map((klass) => (
            <ClassCard key={klass.id} klass={klass} onChanged={() => mutate()} />
          ))}
        </div>
      </main>
    </Shell>
  );
}

function MakeClass({
  first,
  onMade,
  onCancel,
}: {
  first: boolean;
  onMade: () => Promise<void>;
  onCancel?: () => void;
}) {
  const [label, setLabel] = useState("");
  const [count, setCount] = useState(25);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!label.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      await api.createClass(label.trim(), count);
      setLabel("");
      await onMade();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <form
      onSubmit={create}
      aria-labelledby="make-class"
      className="no-print mb-8 rounded-[var(--radius-talk)] border border-rule bg-sheet px-4 py-5 sm:px-6"
    >
      <h2 id="make-class" className="font-serif text-lg font-semibold text-ink">
        {first ? "Make your first class" : "Make a class"}
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-pencil">
        Students get numbered names like <span className="whitespace-nowrap">9B-01</span>,{" "}
        <span className="whitespace-nowrap">9B-02</span>. Keep your own list of who is who; the
        platform never stores real names. You can add or remove students later.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1 basis-48">
          <label htmlFor="class-label" className="mb-1 ml-1 block text-sm font-medium text-ink">
            Class name
          </label>
          <input
            id="class-label"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={32}
            placeholder="9B English"
            autoFocus={!first}
            className={`${field} w-full`}
          />
        </div>
        <div>
          <label htmlFor="class-size" className="mb-1 ml-1 block text-sm font-medium text-ink">
            Students
          </label>
          <input
            id="class-size"
            type="number"
            min={0}
            max={40}
            value={count}
            onChange={(e) => setCount(Math.max(0, Math.min(40, Number(e.target.value) || 0)))}
            className={`${field} figures w-24 text-right`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone="primary" type="submit" disabled={creating || !label.trim()} className="h-11">
            {creating ? "Making the class…" : "Make class"}
          </Pill>
          {onCancel && (
            <Button variant="plain" type="button" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
      </div>
      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
    </form>
  );
}

/* ---------- one class ---------- */

function ClassCard({ klass, onChanged }: { klass: ClassOut; onChanged: () => void }) {
  const { data: roster, mutate } = useSWR<RosterEntry[]>(["roster", klass.id], () =>
    api.roster(klass.id),
  );
  // Codes exist only in this response: the server keeps digests, not codes.
  const [issued, setIssued] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Both lists are long and rarely needed; each opens on request.
  const [studentsOpen, setStudentsOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);

  const colour = classColour(klass.label);
  const studentsId = `students-${klass.id}`;
  const progressId = `progress-${klass.id}`;

  async function changed() {
    await mutate();
    onChanged();
    void refresh(["progress", klass.id]);
  }

  async function issue(student?: RosterEntry) {
    // Only replacing a code signs a student out; a first code leaves them signed in.
    const replacing = student ? student.has_join_code : roster?.some((r) => r.has_join_code);
    if (
      replacing &&
      !window.confirm(
        student
          ? `Give ${student.pseudonym} a new code? Their old code stops working and they're signed out.`
          : `Give everyone in ${klass.label} a new code? The old codes stop working, and the students who had one are signed out.`,
      )
    ) {
      return;
    }
    setBusy(student?.student_id ?? "all");
    setError(null);
    try {
      const codes = await api.issueJoinCodes(klass.id, student?.student_id);
      setIssued((prev) => ({
        ...prev,
        ...Object.fromEntries(codes.map((c) => [c.student_id, c.code])),
      }));
      await mutate();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function addStudent() {
    setBusy("add");
    setError(null);
    try {
      await api.addStudent(klass.id);
      setStudentsOpen(true);
      await changed();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeStudent(student: RosterEntry) {
    if (
      !window.confirm(
        `Take ${student.pseudonym} off ${klass.label}? If this is their only class they are signed out now, even mid-lesson, and their code stops working. Their past lessons and work are kept.`,
      )
    ) {
      return;
    }
    setBusy(student.student_id);
    setError(null);
    try {
      await api.removeStudent(klass.id, student.student_id);
      await changed();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  const anyShown = Object.keys(issued).length > 0;
  const withoutCode = roster?.filter((r) => !r.has_join_code).length ?? 0;

  return (
    <section
      aria-labelledby={`class-${klass.id}`}
      className="rounded-[var(--radius-talk)] border border-rule bg-sheet"
    >
      <div className="flex items-center gap-4 px-4 pt-5 pb-4 sm:px-6">
        {/* The class's own colour, the same as beside its name everywhere else. */}
        <span
          aria-hidden="true"
          className="grid size-12 shrink-0 place-items-center rounded-full"
          style={{ backgroundColor: `color-mix(in srgb, ${colour} 14%, white)`, color: colour }}
        >
          <svg
            viewBox="0 0 24 24"
            className="size-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="9" cy="8" r="3.25" />
            <path d="M3 19c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
            <circle cx="17" cy="9" r="2.5" />
            <path d="M16.5 13.6c2.6.2 4.5 2.1 4.5 4.9" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <h2
            id={`class-${klass.id}`}
            className="font-serif text-xl font-semibold break-words text-ink"
          >
            {klass.label}
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-pencil">
            <span className="figures">{plural(klass.students, "student")}</span>
            {roster && roster.length > 0 && (
              <Tag tone={withoutCode === 0 ? "tick" : "amber"}>
                {withoutCode === 0
                  ? "Everyone has a code"
                  : withoutCode === roster.length
                    ? "No codes given out yet"
                    : `${withoutCode} still need a code`}
              </Tag>
            )}
          </p>
        </div>
      </div>

      <div className="no-print flex flex-wrap gap-2 px-4 pb-5 sm:px-6">
        <Pill
          expanded={studentsOpen}
          controls={studentsId}
          onClick={() => setStudentsOpen((v) => !v)}
        >
          {studentsOpen ? "Hide students and codes" : "Show students and codes"}
        </Pill>
        <Pill
          expanded={progressOpen}
          controls={progressId}
          onClick={() => setProgressOpen((v) => !v)}
        >
          {progressOpen ? "Hide how they did" : "Show how they did"}
        </Pill>
        <Pill onClick={addStudent} disabled={busy !== null}>
          <Plus />
          {busy === "add" ? "Adding…" : "Add a student"}
        </Pill>
      </div>

      {error && (
        <div className="px-4 pb-4 sm:px-6">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {studentsOpen && (
        <div id={studentsId} className="border-t border-rule px-4 py-5 sm:px-6">
          <h3 className="mb-3 text-base font-bold text-ink">Students and sign-in codes</h3>
          {!roster && <Skeleton label={`Loading ${klass.label}`} rows={2} />}
          {roster?.length === 0 && (
            <Empty>No students are in this class yet. Add a student to give them a code.</Empty>
          )}
          {roster && roster.length > 0 && (
            <>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sheet)] bg-sunken px-4 py-3">
                <p className="min-w-0 flex-1 basis-64 text-sm text-ink">
                  A code is how a student signs in: they type it on the student sign-in page, with
                  no name or password. Each code belongs to one student.
                </p>
                <Pill onClick={() => issue()} disabled={busy !== null} className="no-print">
                  {busy === "all"
                    ? "Making codes…"
                    : roster.some((r) => r.has_join_code)
                      ? "New codes for everyone"
                      : "Make codes for everyone"}
                </Pill>
              </div>
              {anyShown && (
                <div className="mb-4">
                  <Notice tone="amber">
                    You&apos;ll only see these codes once. Write them down or{" "}
                    <button
                      onClick={() => window.print()}
                      className="font-semibold underline underline-offset-4"
                    >
                      print this page
                    </button>{" "}
                    before you leave.
                  </Notice>
                </div>
              )}
              <div className="relative overflow-x-auto rounded-[var(--radius-sheet)] border border-rule">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-pencil">
                      <th scope="col" className="py-2.5 pr-3 pl-4 font-semibold">
                        Student
                      </th>
                      <th scope="col" className="px-3 py-2.5 font-semibold">
                        Sign-in code
                      </th>
                      <th scope="col" className="py-2.5 pr-4 pl-3">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {roster.map((student) => (
                      <tr key={student.student_id} className="border-t border-rule">
                        <th
                          scope="row"
                          className="figures py-3 pr-3 pl-4 text-left font-bold whitespace-nowrap text-ink"
                        >
                          {student.pseudonym}
                        </th>
                        <td className="px-3 py-3">
                          {issued[student.student_id] ? (
                            <span className="figures text-lg font-bold tracking-[0.12em] whitespace-nowrap text-ink">
                              {issued[student.student_id]}
                            </span>
                          ) : student.has_join_code ? (
                            <Tag tone="tick">Given out</Tag>
                          ) : (
                            <Tag tone="amber">No code yet</Tag>
                          )}
                        </td>
                        {/* The two buttons stack on a phone rather than run off the card. */}
                        <td className="py-3 pr-4 pl-3">
                          <div className="flex flex-wrap justify-end gap-x-4 gap-y-1">
                            <Button
                              variant="plain"
                              onClick={() => issue(student)}
                              disabled={busy !== null}
                              className="no-print text-sm"
                            >
                              {busy === student.student_id
                                ? "Making code…"
                                : student.has_join_code
                                  ? "New code"
                                  : "Make a code"}
                            </Button>
                            <Button
                              variant="plain"
                              onClick={() => removeStudent(student)}
                              disabled={busy !== null}
                              className="no-print text-sm"
                            >
                              Remove
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {progressOpen && (
        <div id={progressId} className="border-t border-rule px-4 py-5 sm:px-6">
          <h3 className="mb-1 text-base font-bold text-ink">How they did, lesson by lesson</h3>
          <ProgressGrid klass={klass} roster={roster} />
        </div>
      )}
    </section>
  );
}

/* ---------- how they did ---------- */

const CELL_LOOK: Record<ProgressCell["state"], { text: string; dot: string; cell: string }> = {
  finished: { text: "text-tick", dot: "bg-tick", cell: "" },
  part: { text: "text-ink", dot: "bg-progress", cell: "" },
  opened: { text: "text-pencil", dot: "border-[1.5px] border-pencil", cell: "" },
  not_started: { text: "text-faint", dot: "bg-rule-strong", cell: "" },
  not_in_lesson: { text: "text-faint", dot: "border border-rule-strong", cell: "bg-sunken/60" },
};

function cellWord(cell: ProgressCell): string {
  switch (cell.state) {
    case "finished":
      return "Finished";
    case "part":
      return cell.steps_total > 0
        ? `${cell.steps_done} of ${cell.steps_total} steps`
        : "Took part";
    case "opened":
      return "Opened only";
    case "not_started":
      return "Not started";
    case "not_in_lesson":
      return "Not in class";
  }
}

function ProgressGrid({ klass, roster }: { klass: ClassOut; roster?: RosterEntry[] }) {
  const { data, error } = useSWR<ClassProgress>(["progress", klass.id], () =>
    api.classProgress(klass.id),
  );

  if (error) return <ErrorNote>{(error as ApiError).message}</ErrorNote>;
  if (!data) return <Skeleton label={`Loading how ${klass.label} did`} rows={2} />;
  if (data.lessons.length === 0) {
    return (
      <Empty>
        No lessons with this class yet. Once you start a lesson with {klass.label}, it shows up
        here.
      </Empty>
    );
  }
  if (data.students.length === 0) return <Empty>No students are in this class yet.</Empty>;

  const onRoster = roster ? new Set(roster.map((r) => r.student_id)) : null;

  return (
    <>
      <p className="mb-4 max-w-2xl text-sm text-pencil">
        One column for each lesson, oldest on the left. A mark shows once you have confirmed it.
        Summary opens that lesson&apos;s end-of-lesson summary, with a note on each student.
      </p>
      {/* Relative, so the screen-reader words in the cells scroll inside this box, not the page. */}
      {/* As wide as its lessons, up to the card: one lesson does not stretch the name column. */}
      <div className="relative w-fit max-w-full overflow-x-auto rounded-[var(--radius-sheet)] border border-rule">
        <table className="w-max border-separate border-spacing-0 text-sm">
          <caption className="sr-only">
            How each student in {klass.label} did in each lesson, oldest lesson first
          </caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 border-r border-rule bg-sheet px-4 py-3 text-left align-bottom text-xs font-semibold text-pencil"
              >
                Student
              </th>
              {data.lessons.map((lesson) => (
                <th
                  key={lesson.session_id}
                  scope="col"
                  className="w-40 min-w-40 px-3 py-3 text-left align-top font-normal"
                >
                  <span
                    title={lesson.title}
                    className="line-clamp-3 font-semibold break-words whitespace-normal text-ink"
                  >
                    {lesson.title || "Untitled lesson"}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-pencil">
                    <span className="figures">{shortDate(lesson.date)}</span>
                    {lesson.status === "open" && <Tag tone="progress">Running</Tag>}
                    {lesson.status === "paused" && <Tag tone="amber">Paused</Tag>}
                  </span>
                  <Link
                    href={`/teacher?outcomes=${lesson.session_id}`}
                    className="no-print mt-1.5 inline-block text-xs font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                  >
                    Summary
                    <span className="sr-only"> of {lesson.title || "this lesson"}</span>
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.students.map((student) => (
              <tr key={student.student_id}>
                <th
                  scope="row"
                  className="figures sticky left-0 z-10 border-t border-r border-rule bg-sheet px-4 py-3 text-left align-top font-bold whitespace-nowrap text-ink"
                >
                  {student.pseudonym}
                  {onRoster && !onRoster.has(student.student_id) && (
                    <span className="block text-xs font-normal text-faint">Left the class</span>
                  )}
                </th>
                {student.cells.map((cell) => {
                  const look = CELL_LOOK[cell.state];
                  return (
                    <td
                      key={cell.session_id}
                      className={`border-t border-rule px-3 py-3 align-top ${look.cell}`}
                    >
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap ${look.text}`}
                      >
                        <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${look.dot}`} />
                        {cellWord(cell)}
                      </span>
                      {cell.mark && (
                        <span className="figures mt-1 block text-sm font-bold text-ink">
                          <span className="sr-only">Mark </span>
                          {cell.mark.total} / {cell.mark.out_of}
                        </span>
                      )}
                      {!cell.mark && cell.outcome === "suggested" && (
                        <span className="mt-1 block text-xs text-amber">Note to check</span>
                      )}
                      {cell.alerts_open > 0 && (
                        <span className="mt-1 block text-xs font-semibold text-red-pen">
                          Needs you
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
