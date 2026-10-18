"use client";

import Link from "next/link";
import { useState } from "react";
import type {
  ConversationItem,
  ResearchConversation,
  ResearchGroupRow,
  ResearchLesson,
  ResearchOverview,
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
const OUTCOME_WORDS: Record<string, string> = {
  ok: "went out as it was",
  regenerated: "sent back, the second draft went out",
  withheld: "held back by the server",
};

const SHEET = "rounded-[var(--radius-sheet)] border border-rule bg-sheet";
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
              {[head, "Lessons", "Students", "Finished", "Turns per student", "Help per student", "Answers given", "Checks failed", "Alerts", "Mean mark"].map((h) => (
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
                <td className={`${TD} font-semibold`}>{c.mean_mark_percent === null ? "none yet" : `${c.mean_mark_percent}%`}</td>
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
    { label: "Agent turns", value: t.turns.toLocaleString(), note: `${per} per student · ${seconds(t.mean_latency_ms)} a reply` },
    { label: "Help given", value: t.hints + t.worked_steps, note: `${t.hints} hints · ${t.worked_steps} worked steps` },
    {
      label: "Final answers given",
      value: t.answers_given,
      note: t.answers_given ? "stated the answer and reached a student" : "none reached a student",
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
    { label: "Alerts to the teacher", value: t.alerts, note: `${t.alerts_dealt_with} dealt with` },
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
  /** The settings and download box, built by the page because it owns the key and the instructions. */
  settings: React.ReactNode;
}) {
  const [teacher, setTeacher] = useState("");
  const [klass, setKlass] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const teachers = [...new Set(data.lessons.map((l) => l.teacher))].sort();
  const showApproach = data.lessons.some((l) => l.approach !== "Not set");
  const classes = [...new Set(data.lessons.map((l) => l.class_label))].sort();
  const rows = data.lessons.filter(
    (l) =>
      (!teacher || l.teacher === teacher) &&
      (!klass || l.class_label === klass) &&
      (!onlyFlagged || l.answers_given || l.checks_failed || l.alerts > l.alerts_dealt_with),
  );
  const select =
    "h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm text-ink";

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="font-serif text-2xl font-semibold text-ink">Research view</h1>
          <p className="mt-1 text-sm text-pencil">
            What the agent did, lesson by lesson, read from the records. Students appear by
            pseudonym. Nothing here changes anything.
          </p>
        </div>
        {settings}
      </div>

      <Numbers
        items={tallyNumbers(data.totals, { students: data.totals.students, finished: data.totals.finished })}
      />

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
                  {["When", "Lesson", "Teacher · class", "Condition", ...(showApproach ? ["Approach"] : []), "Students", "Turns", "Answers given", "Checks failed", "Alerts", ""].map((h, i) => (
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
                      <span className="block text-xs text-pencil">
                        {[l.unit && `${l.unit} unit`, l.status === "closed" ? "ended" : l.status].filter(Boolean).join(" · ")}
                      </span>
                    </td>
                    <td className={TD}>{l.teacher} · {l.class_label}</td>
                    <td className={TD}>{l.condition}</td>
                    {showApproach && <td className={TD}>{l.approach === "Not set" ? <span className="text-pencil">·</span> : l.approach}</td>}
                    <td className={`${TD} whitespace-nowrap`}>{l.took_part} of {l.students}</td>
                    <td className={TD}>{l.turns}</td>
                    <td className={`${TD} ${l.answers_given ? "font-semibold text-red-pen" : "text-pencil"}`}>{l.answers_given}</td>
                    <td className={`${TD} ${l.checks_failed ? "font-semibold text-amber" : "text-pencil"}`}>{l.checks_failed}</td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {l.alerts}
                      {l.alerts > 0 && <span className="text-pencil"> · {l.alerts_dealt_with === l.alerts ? "all dealt with" : `${l.alerts_dealt_with} dealt with`}</span>}
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
        <p className="text-xs font-bold text-pencil">
          {[data.subject, data.unit && `${data.unit} unit`].filter(Boolean).join(" · ")}
        </p>
        <h1 className="font-serif text-2xl font-semibold text-ink">{data.title || "Untitled lesson"}</h1>
        <p className="mt-1 text-sm text-pencil">
          {data.teacher} with {data.class_label} · {dayTime(data.at)}
          {data.closed_at && ` to ${clockTime(data.closed_at)}`} · {data.condition.toLowerCase()}{data.approach !== "Not set" && ` · taught by ${data.approach.toLowerCase()}`} ·{" "}
          {data.models.join(", ")}, prompts {data.prompt_versions.join(", ")}
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
                {["Student", "Got to", "Judged", "Help given", "Checks", "Alert", `Mark (of ${data.mark_max || "–"})`, ""].map((h, i) => (
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
                  <span className="font-semibold">{a.pseudonym}: {words(QUEUE_WORDS, a.kind).toLowerCase()}.</span>{" "}
                  {a.summary}{" "}
                  {a.dealt_with_at ? (
                    <span className="text-pencil">Dealt with at {clockTime(a.dealt_with_at)}.</span>
                  ) : a.status === "open" ? (
                    <span className="font-semibold text-red-pen">Still open.</span>
                  ) : (
                    <span className="text-pencil">Resolved.</span>
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

      <section className={`${SHEET} px-5 py-4`}>
        <h2 className="text-base font-bold text-ink">The raw record</h2>
        <p className="text-xs text-pencil">Every model call in this lesson, with what the agent was shown and its full reply.</p>
        <ResearchTurns researchKey={researchKey} sessionId={data.session_id} label="Open every call" />
      </section>
    </>
  );
}

function StudentRow({ s, sessionId }: { s: ResearchStudentRow; sessionId: string }) {
  const mute = "text-pencil";
  if (!s.took_part) {
    return (
      <tr>
        <td className={`${TD} font-semibold ${mute}`}>{s.pseudonym}</td>
        <td className={`${TD} ${mute}`} colSpan={7}>did not start</td>
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
              <span className={a.status === "open" ? "font-semibold text-red-pen" : ""}>{words(QUEUE_WORDS, a.kind)}</span>
              <span className={`block text-xs ${mute}`}>
                {a.at ? clockTime(a.at) : ""}{a.dealt_with_at ? `, dealt with ${clockTime(a.dealt_with_at)}` : a.status === "open" ? ", still open" : ""}
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

function Tags({ item }: { item: Extract<ConversationItem, { kind: "agent" }> }) {
  const tags: { text: string; tone?: "warn" | "good" }[] = [];
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
  if (item.latency_ms) tags.push({ text: seconds(item.latency_ms) });
  const look = {
    warn: "border-amber/40 bg-amber-wash text-ink",
    good: "border-tick/30 bg-tick-wash text-ink",
    none: "border-rule bg-sheet text-pencil",
  };
  return (
    <ul aria-label="What this turn did" className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
      {tags.map((t, i) => (
        <li key={i} className={`rounded-full border px-2 py-0.5 ${look[t.tone ?? "none"]}`}>{t.text}</li>
      ))}
    </ul>
  );
}

export function ConversationView({ data }: { data: ResearchConversation }) {
  const pre = "mt-2 max-h-72 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink";
  const side = `${SHEET} px-4 py-3`;
  const help = [
    data.items.filter((i) => i.kind === "agent" && i.hint).length,
    data.items.filter((i) => i.kind === "agent" && i.worked_step).length,
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
            {data.turns} turns · got to step {Math.min(reached || 1, data.steps.length)} of {data.steps.length} · {help[0]} hints and {help[1]} worked steps
            {stepped > 0 && ` · the teacher stepped in ${stepped === 1 ? "once" : `${stepped} times`}`}
            {mark !== null && mark !== undefined && ` · mark ${mark} of ${data.mark.max}`} · {data.condition.toLowerCase()}
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
                  <span className="block text-xs font-bold text-pencil">Agent · {time}</span>
                  <Rich text={item.text} />
                </div>
                <Tags item={item} />
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
            {data.earlier.length ? (
              <p className="mt-1 text-ink">
                Records from {data.earlier.map((e) => `${e.title} (${dayTime(e.at)})`).join(", ")}
                {data.memory_used ? "." : ", though this lesson was set not to use them."}
              </p>
            ) : (
              <p className="mt-1 text-pencil">Nothing from earlier lessons.</p>
            )}
          </section>
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
                    {t.what === "alert" && `alerted: ${words(QUEUE_WORDS, t.kind ?? "").toLowerCase()}`}
                    {t.what === "dealt_with" && "pressed Dealt with"}
                    {t.what === "guidance" && `told the agent: “${t.text}”${t.shown_to_student ? " (shown to the student)" : ""}`}
                    {t.what === "read_conversation" && "read the whole conversation"}
                    {t.what === "mark" && `confirmed the mark: ${t.total} of ${data.mark.max}${t.comment ? ` “${t.comment}”` : ""}`}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className={side}>
            <h2 className="font-bold text-ink">Record</h2>
            <p className="mt-1 text-pencil">
              {data.turns} model calls · {data.models.join(", ") || "no model yet"} · prompts {data.prompt_versions.join(", ") || "–"} · {seconds(data.mean_latency_ms)} a reply. Every call lists the records it was shown under the turn.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
