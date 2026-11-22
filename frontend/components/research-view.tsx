"use client";

import Link from "next/link";
import { useState } from "react";
import type {
  ConversationItem,
  Pitch,
  PitchCall,
  ResearchConversation,
  ResearchGroupRow,
  ResearchLesson,
  ResearchOverview,
  ResearchPitching,
  ResearchStudentRow,
  ResearchTally,
} from "@/lib/api";
import { Rich } from "@/components/chat";
import { ResearchTurns } from "@/components/research-turns";
import { Empty, QUEUE_WORDS, clockTime } from "@/components/ui";

/** The researcher's three pages: the whole study, one lesson, one conversation. Numbers and
 * plain words first; the raw record one press away. */

export const CONFLICT_WORDS: Record<string, string> = {
  over_disclosure: "gave more than allowed",
  answer_leakage: "stated the answer",
  wrote_the_work: "wrote the work",
  skipped_assessment: "moved on without judging",
  off_ladder: "help out of ladder order",
  false_claim: "claimed to have done the teacher's job",
  malformed_output: "unreadable reply",
};
const JUDGMENT_WORDS: Record<string, string> = {
  met: "met",
  partial: "partly",
  not_met: "not yet",
  unclear: "unclear",
};
const SIGNAL_WORDS: Record<string, string> = {
  struggling: "struggling",
  misconception: "a misconception",
  manipulation_attempt: "asking for the answer",
  off_task: "off task",
  fast_progress: "racing ahead",
  unresolved_question: "an unresolved question",
  wellbeing: "a wellbeing concern",
  asked_for_teacher: "asking for the teacher",
};
/** Alert kinds as a researcher reads them; the board's own words speak to the teacher. */
const ALERT_WORDS: Record<string, string> = {
  ...QUEUE_WORDS,
  teacher_requested: "Asked for the teacher",
  manipulation: "Trying to get the answer (possible cheating)",
};

const OUTCOME_WORDS: Record<string, string> = {
  ok: "went out as it was",
  regenerated: "sent back, the second draft went out",
  withheld: "held back by the server",
};

const SHEET = "rounded-[var(--radius-sheet)] border border-rule bg-sheet shadow-sheet";
const TH = "py-2 pr-4 text-left text-xs font-bold whitespace-nowrap text-pencil";
const TD = "border-t border-rule py-2.5 pr-4 align-top";
const LINK = "font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink";

function dayTime(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${clockTime(iso)}`;
}
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const words = (map: Record<string, string>, key: string) => map[key] ?? key.replace(/_/g, " ");

/** The big plain numbers along the top of a page. */
function Numbers({
  items,
}: {
  items: { label: string; value: string | number; note?: string; tone?: "red" | "amber" | "tick" }[];
}) {
  const tone = { red: "text-red-pen", amber: "text-amber", tick: "text-tick" };
  return (
    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {items.map((it) => (
        <div key={it.label} className={`${SHEET} px-4 py-3`}>
          <p className="text-xs text-pencil">{it.label}</p>
          <p className={`figures font-serif text-3xl font-semibold leading-tight ${it.tone ? tone[it.tone] : "text-ink"}`}>
            {it.value}
          </p>
          {it.note && <p className="mt-1 text-xs text-pencil">{it.note}</p>}
        </div>
      ))}
    </div>
  );
}

/** Groups of students side by side: the study's conditions, or the teaching approaches. */
function GroupTable({ title, note, head, rows }: { title: string; note: string; head: string; rows: ResearchGroupRow[] }) {
  return (
    <section className={`${SHEET} px-5 py-4`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-bold text-ink">{title}</h2>
        <p className="text-xs text-pencil">{note}</p>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {[head, "Lessons", "Students (each lesson)", "Finished", "Turns per student", "Help per student", "Answers given", "Checks failed", "Alerts", "Said it helped", "Mean mark (confirmed, else suggested)"].map((h) => (
                <th key={h} className={TH}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="text-ink">
            {rows.map((c) => (
              <tr key={c.name}>
                <td className={`${TD} font-semibold`}>{c.name}</td>
                <td className={TD}>{c.lessons}</td>
                <td className={TD}>{c.students}</td>
                <td className={TD}>{c.finished}{c.students ? ` (${Math.round((100 * c.finished) / c.students)}%)` : ""}</td>
                <td className={TD}>{c.turns_per_student}</td>
                <td className={TD}>{c.help_per_student}</td>
                <td className={`${TD} ${c.answers_given ? "font-semibold text-red-pen" : ""}`}>{c.answers_given}</td>
                <td className={TD}>{c.checks_failed}</td>
                <td className={TD}>{c.alerts}</td>
                <td className={TD}>{c.helped + c.not_helped ? `${c.helped} of ${c.helped + c.not_helped}` : <span className="text-pencil">·</span>}</td>
                <td className={`${TD} font-semibold`}>{c.mean_mark_percent === null ? "none yet" : `${c.mean_mark_percent}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** The tutor's calls on how it asked a step, as the table heads them, in the table's order. */
const PITCH_CALLS: Record<PitchCall, string> = {
  "as written": "As written",
  stretched: "Stretched",
  "more support": "More support",
  stayed: "Stayed",
  "let go": "Let go",
};

/** How the tutor pitched steps, one row per model, on the turns it was told it may. */
function Pitching({ rows }: { rows: ResearchPitching[] }) {
  return (
    <section className={`${SHEET} px-5 py-4`}>
      <h2 className="text-base font-bold text-ink">How the tutor pitched</h2>
      <p className="text-xs text-pencil">
        Only turns where the tutor was told it may pitch a step. Each count is the tutor&apos;s own call, as it
        recorded it. Met on its version: a student met the step while the tutor&apos;s own version was the question.
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {["Model", "Turns", ...Object.values(PITCH_CALLS), "Met on its version", "Changed most"].map((h) => (
                <th key={h} className={TH}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="text-ink">
            {rows.map((r) => (
              <tr key={r.model}>
                <td className={`${TD} font-semibold`}>{r.model}</td>
                <td className={TD}>{r.turns}</td>
                {(Object.keys(PITCH_CALLS) as PitchCall[]).map((call) => (
                  <td key={call} className={TD}>{r.calls[call]}</td>
                ))}
                <td className={TD}>{r.met_on_its_version}</td>
                <td className={`${TD} whitespace-nowrap`}>
                  {r.changed.length > 0 ? (
                    r.changed.slice(0, 3).map((c) => `${c.thing} ${c.times}`).join(", ")
                  ) : (
                    <span className="text-pencil">none</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function tallyNumbers(t: ResearchTally, people: { students: number; finished: number; of?: number }) {
  const per = people.students ? (t.turns / people.students).toFixed(0) : "0";
  return [
    {
      label: people.of === undefined ? "Students taught" : "Took part",
      value: people.of === undefined ? people.students : `${people.students} of ${people.of}`,
      note: `${people.finished} finished every step`,
    },
    {
      label: "Agent turns",
      value: t.turns.toLocaleString(),
      note: `${per} per student · ${seconds(t.mean_latency_ms)} a reply${t.helped + t.not_helped ? ` · students: helped ${t.helped}, not ${t.not_helped}` : ""}`,
    },
    {
      label: "Help given",
      value: t.hints + t.worked_steps,
      note: `${t.hints} ${t.hints === 1 ? "hint" : "hints"} · ${t.worked_steps} worked ${t.worked_steps === 1 ? "step" : "steps"}`,
    },
    {
      label: "Answers that reached a pupil",
      value: t.answers_given,
      note: t.answers_given
        ? "stated the answer and reached a student"
        : `none; ${t.checks_failed} first ${t.checks_failed === 1 ? "draft" : "drafts"} caught first`,
      tone: t.answers_given ? ("red" as const) : ("tick" as const),
    },
    {
      label: "Rule checks failed",
      value: t.checks_failed,
      note: t.checks_failed
        ? `${t.checks_fixed} fixed on retry · ${t.held_back} held back`
        : "every reply kept to the rules",
      tone: t.checks_failed ? ("amber" as const) : undefined,
    },
    {
      label: "Alerts to the teacher",
      value: t.alerts,
      note: [
        `${t.alerts_open} open`,
        `${t.alerts_dealt_with} dealt with`,
        t.alerts_cleared ? `${t.alerts_cleared} cleared themselves` : "",
      ]
        .filter(Boolean)
        .join(" · "),
      tone: t.alerts_open ? ("amber" as const) : undefined,
    },
  ];
}

/* ---------- 1. the whole study ---------- */

export function Overview({
  data,
  researchKey,
  settings,
}: {
  data: ResearchOverview;
  researchKey: string;
  /** The study and download box, built by the page because it owns the key and the instructions. */
  settings: React.ReactNode;
}) {
  const [teacher, setTeacher] = useState("");
  const [klass, setKlass] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const teachers = [...new Set(data.lessons.map((l) => l.teacher))].sort();
  const showApproach = data.lessons.some((l) => l.approach !== "Not set");
  // Keyed by teacher as well: eight teachers can each have an 8C.
  const classKey = (l: ResearchOverview["lessons"][number]) => `${l.teacher} · ${l.class_label}`;
  const classes = [...new Set(data.lessons.map(classKey))].sort();
  const rows = data.lessons.filter(
    (l) =>
      (!teacher || l.teacher === teacher) &&
      (!klass || classKey(l) === klass) &&
      (!onlyFlagged || l.answers_given || l.checks_failed || l.alerts_open > 0),
  );
  const select =
    "h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink";

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="font-serif text-2xl font-semibold text-ink">Research view</h1>
          <p className="mt-1 text-sm text-pencil">
            What the agent did in your lessons, read from the records, with every word your
            students wrote. Students appear by pseudonym. Opening a conversation here is noted
            in the lesson record, as it is from the class board. Nothing here changes anything.
          </p>
        </div>
        {settings}
      </div>

      <Numbers
        items={tallyNumbers(data.totals, { students: data.totals.students, finished: data.totals.finished })}
      />

      <details className="mt-3 text-sm text-pencil">
        <summary className="cursor-pointer font-semibold text-ink">How these are counted</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Took part: wrote, or pressed a help button, at least once; the agent&apos;s greeting alone does not count.</li>
          <li>Agent turns: every model call for a pupil, openings and the teacher&apos;s guidance included.</li>
          <li>Help given: hints and worked steps in replies to something the pupil wrote or pressed.</li>
          <li>Answers that reached a pupil: a reply that stated the step&apos;s answer and went out. Checked only where a step has a reference answer; with enforcement on, a first draft that leaks is caught and counted under checks failed instead.</li>
          <li>Checks failed: the agent&apos;s first draft broke a rule; fixed on retry or held back.</li>
          <li>Alerts: everything the agent raised for the teacher, including those cleared by the pupil moving on.</li>
          <li>Mean mark: the teacher&apos;s confirmed total where there is one, else the suggested one.</li>
          {data.pitching?.length ? (
            <>
              <li>How the tutor pitched: only turns where the tutor was told it may pitch a step. Each count is the tutor&apos;s own call, as it recorded it.</li>
              <li>Met on its version: a student met the step while the tutor&apos;s own version was the question.</li>
            </>
          ) : null}
        </ul>
      </details>

      {data.conditions.length > 1 && (
        <GroupTable
          title="By condition"
          note="Same lessons, same classes; the server split the students."
          head="Condition"
          rows={data.conditions}
        />
      )}
      {data.approaches.some((a) => a.name !== "Not set") && (
        <GroupTable
          title="By teaching approach"
          note="Lessons tagged direct instruction or guided inquiry, against the rest."
          head="Approach"
          rows={data.approaches}
        />
      )}

      <section className={`${SHEET} px-5 py-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-ink">Lessons</h2>
            <p className="text-xs text-pencil">Newest first. Press a lesson to see every student in it.</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-pencil">
            {teachers.length > 1 && (
              <label className="flex items-center gap-2">
                Teacher
                <select value={teacher} onChange={(e) => setTeacher(e.target.value)} className={select}>
                  <option value="">All</option>
                  {teachers.map((t) => <option key={t}>{t}</option>)}
                </select>
              </label>
            )}
            {classes.length > 1 && (
              <label className="flex items-center gap-2">
                Class
                <select value={klass} onChange={(e) => setKlass(e.target.value)} className={select}>
                  <option value="">All</option>
                  {classes.map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
            )}
            <label className="flex items-center gap-2 text-ink">
              <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} className="size-4" />
              Only lessons where something needs a look
            </label>
          </div>
        </div>
        {data.lessons.length === 0 ? (
          <Empty>No lesson has had a student turn yet.</Empty>
        ) : rows.length === 0 ? (
          <Empty>Nothing matches.</Empty>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["When", "Lesson", "Teacher · class", ...(data.study.active ? ["Condition"] : []), ...(showApproach ? ["Approach"] : []), "Students", "Turns", "Answers reached", "Checks failed", "Alerts", ""].map((h, i) => (
                    <th key={i} className={TH}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-ink">
                {rows.map((l) => (
                  <tr key={l.session_id}>
                    <td className={`${TD} whitespace-nowrap text-pencil`}>{dayTime(l.at)}</td>
                    <td className={TD}>
                      <Link href={`/research?lesson=${l.session_id}`} className={LINK}>{l.title || "Untitled lesson"}</Link>
                      <span className="block text-xs text-pencil [overflow-wrap:anywhere]">
                        {[l.unit && `Unit: ${l.unit}`, l.status === "closed" ? "ended" : l.status].filter(Boolean).join(" · ")}
                      </span>
                    </td>
                    <td className={TD}>{l.teacher} · {l.class_label}</td>
                    {data.study.active && <td className={TD}>{l.condition}</td>}
                    {showApproach && <td className={TD}>{l.approach === "Not set" ? <span className="text-pencil">·</span> : l.approach}</td>}
                    <td className={`${TD} whitespace-nowrap`}>{l.took_part} of {l.students}</td>
                    <td className={TD}>{l.turns}</td>
                    <td className={`${TD} ${l.answers_given ? "font-semibold text-red-pen" : "text-pencil"}`}>{l.answers_given}</td>
                    <td className={`${TD} ${l.checks_failed ? "font-semibold text-amber" : "text-pencil"}`}>{l.checks_failed}</td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {l.alerts}
                      {l.alerts > 0 && <span className={l.alerts_open ? "font-semibold text-amber" : "text-pencil"}> · {l.alerts_open ? `${l.alerts_open} open` : "none open"}</span>}
                    </td>
                    <td className={`${TD} text-right`}>
                      <Link href={`/research?lesson=${l.session_id}`} className={LINK}>Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data.pitching?.length ? <Pitching rows={data.pitching} /> : null}

      <section className={`${SHEET} px-5 py-4`}>
        <h2 className="text-base font-bold text-ink">Teachers&apos; conversations with the agent</h2>
        <p className="text-xs text-pencil">
          Making lessons, asking about the class, telling it what to do with a student.
        </p>
        <ResearchTurns researchKey={researchKey} label="Read them" />
      </section>
    </>
  );
}

/* ---------- 2. one lesson ---------- */

function StepBoxes({ reached, total, finished }: { reached: number; total: number; finished: boolean }) {
  const done = finished ? total : reached;
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden="true" className="inline-flex gap-0.5">
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={`size-3 rounded-[3px] ${i < done ? "bg-ink" : "border border-rule-strong"}`} />
        ))}
      </span>
      <span className="whitespace-nowrap">{finished ? "finished" : `step ${Math.min(reached + 1, total)} of ${total}`}</span>
    </span>
  );
}

export function LessonView({ data, researchKey }: { data: ResearchLesson; researchKey: string }) {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [sort, setSort] = useState<"look" | "name" | "progress" | "mark">("look");
  const students = data.students
    .filter((s) => !onlyFlagged || s.needs_look)
    .sort((a, b) => {
      if (sort === "name") return a.pseudonym.localeCompare(b.pseudonym);
      if (sort === "progress") return (b.finished ? 99 : b.step_index) - (a.finished ? 99 : a.step_index);
      if (sort === "mark") return (b.mark_confirmed ?? b.mark_suggested ?? -1) - (a.mark_confirmed ?? a.mark_suggested ?? -1);
      return Number(b.needs_look) - Number(a.needs_look) || Number(b.took_part) - Number(a.took_part) || a.pseudonym.localeCompare(b.pseudonym);
    });
  const select =
    "h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink";

  return (
    <>
      <nav aria-label="Where you are" className="text-sm text-pencil">
        <Link href="/research" className="underline decoration-rule-strong underline-offset-4 hover:text-ink">Research</Link>
        <span aria-hidden="true"> › </span>
        <span className="font-semibold text-ink">{data.title}, {dayTime(data.at)}</span>
      </nav>

      <div>
        <p className="text-xs font-bold text-pencil [overflow-wrap:anywhere]">
          {[data.subject, data.unit && `Unit: ${data.unit}`].filter(Boolean).join(" · ")}
        </p>
        <h1 className="font-serif text-2xl font-semibold text-ink">{data.title || "Untitled lesson"}</h1>
        <p className="mt-1 text-sm text-pencil">
          {data.teacher} with {data.class_label} · {dayTime(data.at)}
          {data.closed_at && ` to ${clockTime(data.closed_at)}`} · {data.condition.toLowerCase()}{data.approach !== "Not set" && ` · taught by ${data.approach.toLowerCase()}`} ·{" "}
          {data.models.length > 0 && `${data.models.join(", ")}, prompts ${data.prompt_versions.join(", ")}`}
        </p>
      </div>

      <Numbers
        items={tallyNumbers(data, { students: data.took_part, of: data.students.length, finished: data.finished })}
      />

      <section className={`${SHEET} px-5 py-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-bold text-ink">Every student</h2>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-pencil">
            <label className="flex items-center gap-2">
              Sort by
              <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className={select}>
                <option value="look">Needs a look first</option>
                <option value="name">Name</option>
                <option value="progress">How far they got</option>
                <option value="mark">Mark</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-ink">
              <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} className="size-4" />
              Only students with a flag
            </label>
          </div>
        </div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {["Student", "Got to", "Judged", "Help given", "Checks", "Alert", data.mark_max ? `Mark (of ${data.mark_max})` : "Mark", ""].map((h, i) => (
                  <th key={i} className={TH}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="text-ink">
              {students.map((s) => (
                <StudentRow key={s.student_id} s={s} sessionId={data.session_id} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className={`${SHEET} px-5 py-4`}>
          <h2 className="text-base font-bold text-ink">What the teacher was told, and did</h2>
          {data.alert_list.length === 0 && data.guidance.length === 0 && <Empty>No alerts in this lesson.</Empty>}
          <ol className="mt-2 space-y-2 text-sm text-ink">
            {data.alert_list.map((a) => (
              <li key={a.id} className="grid grid-cols-[3.25rem_1fr] gap-2">
                <span className="text-pencil">{a.at ? clockTime(a.at) : ""}</span>
                <span>
                  <span className="font-semibold">{a.pseudonym}: {words(ALERT_WORDS, a.kind).toLowerCase()}.</span>{" "}
                  {a.summary}{" "}
                  {a.dealt_with_at ? (
                    <span className="text-pencil">Dealt with at {clockTime(a.dealt_with_at)}.</span>
                  ) : a.status === "open" ? (
                    <span className="font-semibold text-red-pen">Still open.</span>
                  ) : (
                    <span className="text-pencil">{a.because ? `Cleared itself: ${a.because}.` : "Resolved."}</span>
                  )}
                </span>
              </li>
            ))}
            {data.guidance.map((g, i) => (
              <li key={i} className="grid grid-cols-[3.25rem_1fr] gap-2">
                <span className="text-pencil">{g.at ? clockTime(g.at) : ""}</span>
                <span>
                  Told the agent about <span className="font-semibold">{g.pseudonym}</span>: “{g.text}”
                  {g.shown_to_student && <span className="text-pencil"> (the student saw it too)</span>}
                </span>
              </li>
            ))}
          </ol>
        </section>
        <section className={`${SHEET} px-5 py-4`}>
          <h2 className="text-base font-bold text-ink">What the checks caught</h2>
          <p className="text-xs text-pencil">
            The server reads every reply before a student sees it. A failed first draft is sent back once
            when checks are enforced; otherwise it is recorded and goes out.
          </p>
          {data.checks.length === 0 && <Empty>Every reply kept to the rules.</Empty>}
          <ol className="mt-2 space-y-2 text-sm text-ink">
            {data.checks.map((c, i) => (
              <li key={i} className="grid grid-cols-[3.25rem_1fr] gap-2">
                <span className="text-pencil">{c.at ? clockTime(c.at) : ""}</span>
                <span>
                  <Link href={`/research?lesson=${data.session_id}&student=${c.student_id}`} className={LINK}>{c.pseudonym}</Link>
                  {c.step_index !== null && <span className="text-pencil">, step {c.step_index + 1}</span>}.{" "}
                  First draft {c.conflicts.map((k) => words(CONFLICT_WORDS, k)).join(" and ")}:{" "}
                  {words(OUTCOME_WORDS, c.outcome)}.
                  {c.retried_because && <span className="block text-xs text-pencil">{c.retried_because}</span>}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      {data.pitching?.length ? <Pitching rows={data.pitching} /> : null}

      <section className={`${SHEET} px-5 py-4`}>
        <h2 className="text-base font-bold text-ink">The raw record</h2>
        <p className="text-xs text-pencil">Every model call in this lesson, with what the agent was shown and its full reply.</p>
        <ResearchTurns researchKey={researchKey} sessionId={data.session_id} label="Open every call" />
      </section>
    </>
  );
}

/** What became of an alert: dealt with by the teacher, closed by what the student did, or open. */
function alertFate(a: ResearchStudentRow["alerts"][number]): string {
  if (a.dealt_with_at) return `, dealt with ${clockTime(a.dealt_with_at)}`;
  if (a.status === "open") return ", still open";
  return a.because ? `, cleared itself: ${a.because}` : ", resolved";
}

function AlertList({ alerts }: { alerts: ResearchStudentRow["alerts"] }) {
  if (alerts.length === 0) return <span className="text-pencil">none</span>;
  return (
    <>
      {alerts.map((a, i) => (
        <span key={i} className="block">
          <span className={a.status === "open" ? "font-semibold text-red-pen" : ""}>{words(ALERT_WORDS, a.kind)}</span>
          <span className="block text-xs text-pencil">{a.at ? clockTime(a.at) : ""}{alertFate(a)}</span>
        </span>
      ))}
    </>
  );
}

function StudentRow({ s, sessionId }: { s: ResearchStudentRow; sessionId: string }) {
  const mute = "text-pencil";
  if (!s.took_part) {
    return (
      <tr className={s.needs_look ? "bg-amber-wash/60" : undefined}>
        <td className={`${TD} font-semibold ${mute}`}>{s.pseudonym}</td>
        <td className={`${TD} ${mute}`} colSpan={4}>did not start</td>
        <td className={TD}><AlertList alerts={s.alerts} /></td>
        <td className={TD} colSpan={2} />
      </tr>
    );
  }
  const mark =
    s.mark_confirmed !== null ? (
      <>
        {s.mark_confirmed} <span className={mute}>confirmed</span>
        {s.mark_suggested !== null && s.mark_suggested !== s.mark_confirmed && (
          <span className={`block text-xs ${mute}`}>agent said {s.mark_suggested}</span>
        )}
      </>
    ) : s.mark_suggested !== null ? (
      <>
        {s.mark_suggested} <span className={mute}>suggested</span>
      </>
    ) : (
      <span className={mute}>not marked</span>
    );
  const help = [
    s.hints && `${s.hints} hint${s.hints === 1 ? "" : "s"}`,
    s.worked_steps && `${s.worked_steps} worked step${s.worked_steps === 1 ? "" : "s"}`,
    s.answers_given && `${s.answers_given} answer${s.answers_given === 1 ? "" : "s"} given`,
  ].filter(Boolean);
  return (
    <tr className={s.needs_look ? "bg-amber-wash/60" : undefined}>
      <td className={`${TD} font-semibold`}>{s.pseudonym}</td>
      <td className={TD}><StepBoxes reached={s.step_index} total={s.steps_total} finished={s.finished} /></td>
      <td className={TD}>
        {s.judgments.some(Boolean) ? s.judgments.map((j, i) => (j ? `${i + 1} ${words(JUDGMENT_WORDS, j)}` : null)).filter(Boolean).join(" · ") : <span className={mute}>nothing yet</span>}
      </td>
      <td className={TD}>
        {help.length ? help.join(", ") : <span className={mute}>none</span>}
        {s.guided > 0 && <span className={`block text-xs ${mute}`}>the teacher stepped in {s.guided === 1 ? "once" : `${s.guided} times`}</span>}
        {s.helped + s.not_helped > 0 && <span className={`block text-xs ${mute}`}>said it helped {s.helped}, not really {s.not_helped}</span>}
      </td>
      <td className={TD}>
        {s.checks_failed ? (
          <>
            <span className="font-semibold text-amber">{s.checks_failed} failed</span>
            <span className={`block text-xs ${mute}`}>{s.check_kinds.map((k) => words(CONFLICT_WORDS, k)).join(", ")}</span>
          </>
        ) : (
          <span className={mute}>none</span>
        )}
      </td>
      <td className={TD}>
        {s.alerts.length === 0 ? (
          <span className={mute}>none</span>
        ) : (
          s.alerts.map((a, i) => (
            <span key={i} className="block">
              <span className={a.status === "open" ? "font-semibold text-red-pen" : ""}>{words(ALERT_WORDS, a.kind)}</span>
              <span className={`block text-xs ${mute}`}>
                {a.at ? clockTime(a.at) : ""}{alertFate(a)}
              </span>
            </span>
          ))
        )}
      </td>
      <td className={TD}>{mark}</td>
      <td className={`${TD} text-right`}>
        <Link href={`/research?lesson=${sessionId}&student=${s.student_id}`} className={LINK}>Read</Link>
      </td>
    </tr>
  );
}

/* ---------- 3. one conversation ---------- */

type Pill = { text: string; tone?: "warn" | "good" };
const PILL_LOOK = {
  warn: "border-amber/40 bg-amber-wash text-ink",
  good: "border-tick/30 bg-tick-wash text-ink",
  none: "border-rule bg-sheet text-pencil",
};

/** The small rounded tags under an agent turn. */
function Pills({ label, tags, className = "" }: { label: string; tags: Pill[]; className?: string }) {
  return (
    <ul aria-label={label} className={`flex flex-wrap gap-1.5 text-xs ${className}`}>
      {tags.map((t, i) => (
        <li key={i} className={`rounded-full border px-2 py-0.5 ${PILL_LOOK[t.tone ?? "none"]}`}>{t.text}</li>
      ))}
    </ul>
  );
}

function Tags({ item }: { item: Extract<ConversationItem, { kind: "agent" }> }) {
  const tags: Pill[] = [];
  if (item.withheld) tags.push({ text: "held back by the server", tone: "warn" });
  if (typeof item.step_index === "number") tags.push({ text: `step ${item.step_index + 1}` });
  if (item.hint) tags.push({ text: "hint" });
  if (item.worked_step) tags.push({ text: "worked step" });
  if (item.answer) tags.push({ text: item.allowed === "full" ? "the answer, allowed now" : "the answer", tone: item.allowed === "full" ? undefined : "warn" });
  if (item.judgment) tags.push({ text: `judged: ${words(JUDGMENT_WORDS, item.judgment)}`, tone: item.judgment === "met" ? "good" : undefined });
  if (item.step_done) tags.push({ text: "moved on", tone: "good" });
  for (const s of item.signals ?? []) tags.push({ text: `noticed ${words(SIGNAL_WORDS, s.kind)}${s.told ? ", told the teacher" : ", noted only"}`, tone: s.told ? "warn" : undefined });
  if (item.conflicts?.length)
    tags.push({ text: `check failed: ${item.conflicts.map((k) => words(CONFLICT_WORDS, k)).join(", ")} · ${words(OUTCOME_WORDS, item.outcome ?? "ok")}`, tone: "warn" });
  if (item.guided) tags.push({ text: "as the teacher asked" });
  if (item.helped === true) tags.push({ text: "student: that helped", tone: "good" });
  if (item.helped === false) tags.push({ text: "student: not really", tone: "warn" });
  if (item.latency_ms) tags.push({ text: seconds(item.latency_ms) });
  return <Pills label="What this turn did" tags={tags} className="mt-1.5" />;
}

/** The tutor's own note on how it asked this step: its call and what it changed as tags, then its
 * line. Kept with the message for the teacher and research; the student never saw it. */
function PitchNote({ pitch }: { pitch: Pitch }) {
  const tags: Pill[] = [
    ...(pitch.call ? [{ text: pitch.call }] : []),
    ...pitch.changed.map((thing) => ({ text: `changed ${thing}` })),
  ];
  const line = pitch.line.trim();
  if (tags.length === 0 && !line) return null;
  return (
    <div className="mt-1.5 text-xs text-pencil">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">Why it asked this way:</span>
        {tags.length > 0 && <Pills label="How it pitched this step" tags={tags} />}
      </div>
      {line && <p className="mt-1 [overflow-wrap:anywhere]">{line}</p>}
    </div>
  );
}

export function ConversationView({ data }: { data: ResearchConversation }) {
  const pre = "mt-2 max-h-72 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink";
  const side = `${SHEET} px-4 py-3`;
  const help = [
    data.items.filter((i) => i.kind === "agent" && i.hint && i.answered).length,
    data.items.filter((i) => i.kind === "agent" && i.worked_step && i.answered).length,
  ];
  const reached = data.steps.filter((s) => s.reached).length;
  const stepped = data.teacher.filter((t) => t.what === "guidance").length;
  const mark = data.mark.confirmed ?? data.mark.suggested;

  return (
    <>
      <nav aria-label="Where you are" className="text-sm text-pencil">
        <Link href="/research" className="underline decoration-rule-strong underline-offset-4 hover:text-ink">Research</Link>
        <span aria-hidden="true"> › </span>
        <Link href={`/research?lesson=${data.session_id}`} className="underline decoration-rule-strong underline-offset-4 hover:text-ink">{data.title}, {dayTime(data.at)}</Link>
        <span aria-hidden="true"> › </span>
        <span className="font-semibold text-ink">{data.pseudonym}</span>
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-2xl font-semibold text-ink">
            {data.pseudonym} <span className="font-sans text-base font-semibold text-pencil">· {data.title} · {dayTime(data.at)}</span>
          </h1>
          <p className="mt-1 text-sm text-pencil">
            {data.turns === 0
              ? "did not start"
              : `${data.turns} turn${data.turns === 1 ? "" : "s"} · got to step ${Math.min(reached || 1, data.steps.length)} of ${data.steps.length} · ${help[0]} hint${help[0] === 1 ? "" : "s"} and ${help[1]} worked step${help[1] === 1 ? "" : "s"}`}
            {stepped > 0 && ` · the teacher stepped in ${stepped === 1 ? "once" : `${stepped} times`}`}
            {mark !== null && mark !== undefined && ` · ${data.mark.confirmed === null ? "suggested mark" : "mark"} ${mark} of ${data.mark.max}`} · {data.condition.toLowerCase()}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          {data.previous && (
            <Link href={`/research?lesson=${data.session_id}&student=${data.previous.student_id}`} className={`${LINK} no-underline rounded-[var(--radius-control)] border border-rule-strong px-3 py-1.5`}>
              Previous: {data.previous.pseudonym}
            </Link>
          )}
          {data.next && (
            <Link href={`/research?lesson=${data.session_id}&student=${data.next.student_id}`} className={`${LINK} no-underline rounded-[var(--radius-control)] border border-rule-strong px-3 py-1.5`}>
              Next: {data.next.pseudonym}
            </Link>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <section aria-label="The conversation" className={`${SHEET} min-w-0 flex-[999_1_32rem] space-y-4 px-5 py-4`}>
          {data.items.length === 0 && <Empty>This student has not written anything yet.</Empty>}
          {data.items.map((item, i) => {
            const time = item.at ? clockTime(item.at) : "";
            if (item.kind === "student")
              return (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-[var(--radius-talk)] bg-sunken px-4 py-2 text-sm text-ink">
                    <span className="block text-xs font-bold text-pencil">{data.pseudonym} · {time}</span>
                    <Rich text={item.text} />
                  </div>
                </div>
              );
            if (item.kind === "event")
              return (
                <p key={i} className="text-center text-xs text-pencil">
                  {time} · {item.text}{item.teacher_only && " (the student did not see this)"}
                </p>
              );
            return (
              <div key={i}>
                <div className="text-sm text-ink">
                  <span className="block text-xs font-bold text-pencil">
                    Agent · {time}
                    {typeof item.words === "number" && (
                      // The count beside the limit the step gave; over it is said in words.
                      <span className="font-normal">
                        {" "}
                        · {item.words} words
                        {typeof item.word_limit === "number" &&
                          ` (limit ${item.word_limit}${item.words > item.word_limit ? ", over" : ""})`}
                      </span>
                    )}
                  </span>
                  <Rich text={item.text} />
                </div>
                <Tags item={item} />
                {item.pitch && <PitchNote pitch={item.pitch} />}
                {item.shown && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs font-semibold text-pencil hover:text-ink">
                      What the agent was shown, and its full reply
                    </summary>
                    <p className="mt-2 text-xs text-pencil">The records the server put in front of the model for this call, by id.</p>
                    <pre className={pre}>{JSON.stringify(item.shown, null, 2)}</pre>
                    <p className="mt-2 text-xs text-pencil">The reply exactly as the model sent it.</p>
                    <pre className={pre}>{typeof item.raw === "string" ? item.raw : JSON.stringify(item.raw, null, 2)}</pre>
                  </details>
                )}
              </div>
            );
          })}
        </section>

        <aside aria-label="Around the conversation" className="flex w-full max-w-sm flex-[1_1_18rem] flex-col gap-3 text-sm">
          <section className={side}>
            <h2 className="font-bold text-ink">Steps</h2>
            <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-ink">
              {data.steps.map((s, i) => (
                <li key={i}>
                  {s.name} ·{" "}
                  {s.judgment ? (
                    <span className={`font-semibold ${s.judgment === "met" ? "text-tick" : "text-amber"}`}>{words(JUDGMENT_WORDS, s.judgment)}</span>
                  ) : s.reached ? (
                    <span className="text-pencil">not judged yet</span>
                  ) : (
                    <span className="text-pencil">not reached</span>
                  )}
                  {s.attempts > 0 && <span className="text-pencil"> · {s.attempts} {s.attempts === 1 ? "try" : "tries"}</span>}
                </li>
              ))}
            </ol>
          </section>
          <section className={side}>
            <h2 className="font-bold text-ink">What the agent knew about {data.pseudonym}</h2>
            {data.remembered.map((r, i) => (
              <div key={i} className="mt-1">
                <p className="text-pencil">
                  The tutor was told this on {r.turns} {r.turns === 1 ? "turn" : "turns"}:
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink">
                  {r.lines.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
            ))}
            {data.earlier.length > 0 && (
              <p className="mt-1 text-ink">
                Records from {data.earlier.map((e) => `${e.title} (${dayTime(e.at)})`).join(", ")}
                {data.memory_used ? "." : ", though this lesson was set not to use them."}
              </p>
            )}
            {data.remembered.length === 0 && data.earlier.length === 0 && (
              <p className="mt-1 text-pencil">Nothing from earlier lessons.</p>
            )}
          </section>
          {data.note && (
            <section className={side}>
              <h2 className="font-bold text-ink">What the tutor remembers about {data.pseudonym}</h2>
              <p className="mt-1 text-pencil">
                The note as it stands now (version {data.note.version}). It can be newer than what this lesson was told.
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink">
                {data.note.learns.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
                {data.note.knows.map((k) => (
                  <li key={k.subject}>
                    In {k.subject}: {k.lines.join(" ")}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className={side}>
            <h2 className="font-bold text-ink">The rules in force</h2>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink">
              {data.rules.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </section>
          <section className={side}>
            <h2 className="font-bold text-ink">The teacher&apos;s part</h2>
            {data.teacher.length === 0 ? (
              <p className="mt-1 text-pencil">The teacher was not involved with this student.</p>
            ) : (
              <ul className="mt-1 space-y-0.5 text-ink">
                {data.teacher.map((t, i) => (
                  <li key={i}>
                    <span className="text-pencil">{t.at ? clockTime(t.at) : ""}</span>{" "}
                    {t.what === "alert" && `alerted: ${words(ALERT_WORDS, t.kind ?? "").toLowerCase()}`}
                    {t.what === "dealt_with" && "pressed Dealt with"}
                    {t.what === "guidance" && `told the agent: “${t.text}”${t.shown_to_student ? " (shown to the student)" : ""}`}
                    {t.what === "read_conversation" && "read the whole conversation"}
                    {t.what === "cleared" && `${words(ALERT_WORDS, t.kind ?? "").toLowerCase()} cleared itself: ${t.text}`}
                    {t.what === "mark" && `confirmed the mark: ${t.total} of ${data.mark.max}${t.comment ? ` “${t.comment}”` : ""}`}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className={side}>
            <h2 className="font-bold text-ink">Record</h2>
            <p className="mt-1 text-pencil">
              {data.turns} model call{data.turns === 1 ? "" : "s"} · {data.models.join(", ") || "no model yet"} · prompts {data.prompt_versions.join(", ") || "none yet"} · {seconds(data.mean_latency_ms)} a reply. Every call lists the records it was shown under the turn.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
