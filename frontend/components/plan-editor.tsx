"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  HINTABLE_RUNGS,
  type ContractIn,
  type Criterion,
  type ItemIn,
  type ItemKind,
  type Phase,
  type PlanDetail,
  type Rung,
} from "@/lib/api";
import { Button, ErrorNote, Notice, Panel, Skeleton } from "@/components/ui";

const SUBJECTS = [
  "mathematics",
  "science",
  "english",
  "history",
  "geography",
  "languages",
  "arts",
  "other",
] as const;

const RUNG_LABEL: Record<Rung, string> = {
  attempt: "no help, they work alone",
  diagnostic_question: "a question back",
  conceptual_cue: "a cue",
  targeted_hint: "a hint",
  analogous_example: "a similar example",
  partial_step: "part of a step, or model sentences",
  full_solution: "the full answer",
};

const DEFAULT_TIMELINE: Phase[] = [
  { name: "Explanation", minutes: 10, tutors_on: false },
  { name: "Tutor time", minutes: 30, tutors_on: true },
  { name: "Class discussion", minutes: 10, tutors_on: false },
];

const DEFAULT_RUBRIC: Criterion[] = [
  { name: "Content", max: 4, description: "" },
  { name: "Language", max: 3, description: "" },
  { name: "Structure", max: 3, description: "" },
];

function emptyItem(kind: ItemKind = "short_answer"): ItemIn {
  return {
    kind,
    prompt: "",
    expected_answer: kind === "short_answer" ? "" : null,
    rubric: kind === "written_response" ? { criteria: DEFAULT_RUBRIC.map((c) => ({ ...c })) } : null,
    hint_templates: {},
    misconception_vocabulary: [],
  };
}

const field =
  "block h-10 w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none";
const label = "mb-1 block text-sm font-medium text-ink";
const removeLink = "text-xs text-pencil underline underline-offset-2 hover:text-ink";

/**
 * Writes a new plan, or edits one. An approved plan is never changed in place:
 * editing it opens its next version as a draft, so lessons already taught keep
 * pointing at exactly what the class was held to.
 */
export function PlanEditor({ planId }: { planId?: string }) {
  const router = useRouter();
  const [loaded, setLoaded] = useState<PlanDetail | null>(null);
  const [loading, setLoading] = useState(Boolean(planId));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "approve" | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState<string>("mathematics");
  const [objectiveCode, setObjectiveCode] = useState("");
  const [notes, setNotes] = useState("");
  const [timeline, setTimeline] = useState<Phase[]>(DEFAULT_TIMELINE);
  const [maxRung, setMaxRung] = useState<Rung>("partial_step");
  const [allowFull, setAllowFull] = useState(false);
  const [repeatedIncorrect, setRepeatedIncorrect] = useState(3);
  const [confidenceFloor, setConfidenceFloor] = useState(0.45);
  const [items, setItems] = useState<ItemIn[]>([emptyItem()]);

  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    (async () => {
      try {
        let plan = await api.plan(planId);
        if (plan.status !== "draft") {
          // Editing an approved plan: open (or reuse) its next draft version.
          const draft = await api.newPlanVersion(planId);
          if (draft.id !== planId) {
            router.replace(`/teacher/contracts/${draft.id}`);
            return;
          }
          plan = await api.plan(draft.id);
        }
        if (cancelled) return;
        setLoaded(plan);
        setTitle(plan.title);
        setSubject(plan.subject);
        setObjectiveCode(plan.objective_code);
        setNotes(plan.notes);
        setTimeline(plan.timeline.length ? plan.timeline : DEFAULT_TIMELINE);
        setMaxRung(plan.max_rung as Rung);
        setAllowFull(plan.allow_full_solution);
        setRepeatedIncorrect(plan.repeated_incorrect);
        setConfidenceFloor(plan.confidence_floor);
        setItems(plan.item_list.length ? plan.item_list : [emptyItem()]);
      } catch (e) {
        if (!cancelled) setError((e as ApiError).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [planId, router]);

  function patchItem(index: number, patch: Partial<ItemIn>) {
    setItems((all) => all.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  function patchPhase(index: number, patch: Partial<Phase>) {
    setTimeline((all) => all.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function body(): ContractIn {
    return {
      title,
      subject,
      objective_code: objectiveCode,
      objective_title: title,
      max_rung: maxRung,
      allow_full_solution: allowFull,
      repeated_incorrect: repeatedIncorrect,
      repeated_misconception: 2,
      confidence_floor: confidenceFloor,
      notes,
      timeline,
      items: items.map((it) => ({
        ...it,
        expected_answer: it.kind === "written_response" ? null : it.expected_answer,
        rubric: it.kind === "written_response" ? it.rubric : null,
        hint_templates: Object.fromEntries(
          Object.entries(it.hint_templates).filter(([, v]) => v && v.trim()),
        ),
        misconception_vocabulary: it.misconception_vocabulary.filter((m) => m.code.trim() && m.label.trim()),
      })),
    };
  }

  async function save(approveAfter: boolean) {
    if (busy) return;
    setBusy(approveAfter ? "approve" : "save");
    setError(null);
    try {
      const saved = loaded ? await api.updatePlan(loaded.id, body()) : await api.createPlan(body());
      if (approveAfter) {
        await api.approvePlan(saved.id);
        router.push("/teacher/contracts");
        return;
      }
      if (!loaded) {
        router.replace(`/teacher/contracts/${saved.id}`);
        return;
      }
      setSavedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }));
    } catch (e) {
      setError((e as ApiError).message);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Skeleton label="Loading the lesson plan" rows={5} />;

  const totalMinutes = timeline.reduce((n, p) => n + (Number(p.minutes) || 0), 0);
  const hasTutorPhase = timeline.some((p) => p.tutors_on);

  return (
    <>
      {loaded && loaded.version > 1 && (
        <div className="mb-4">
          <Notice tone="amber">
            You&apos;re editing version {loaded.version}, a draft. Classes keep using version{" "}
            {loaded.approved_version ?? loaded.version - 1} until you approve this one.
          </Notice>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(false);
        }}
        className="space-y-5"
      >
        <Panel title="The lesson">
          <div className="space-y-3">
            <div>
              <label htmlFor="title" className={label}>
                Title
              </label>
              <input
                id="title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Argumentative paragraphs: choosing a career"
                className={field}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="subject" className={label}>
                  Subject
                </label>
                <select id="subject" value={subject} onChange={(e) => setSubject(e.target.value)} className={field}>
                  {!SUBJECTS.includes(subject as (typeof SUBJECTS)[number]) && <option value={subject}>{subject}</option>}
                  {SUBJECTS.map((s) => (
                    <option key={s} value={s}>
                      {s.charAt(0).toUpperCase() + s.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="code" className={label}>
                  Objective code
                </label>
                <input
                  id="code"
                  required
                  value={objectiveCode}
                  onChange={(e) => setObjectiveCode(e.target.value)}
                  placeholder="ENG-ARG-P"
                  className={field}
                />
                <p className="mt-1 text-xs text-faint">How a student&apos;s past work on this skill is found later.</p>
              </div>
            </div>
            <div>
              <label htmlFor="notes" className={label}>
                Material the tutor may use <span className="font-normal text-faint">(students see it too)</span>
              </label>
              <textarea
                id="notes"
                rows={5}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="What you put on the board: the structure, key ideas, a worked example."
                className={`${field} h-auto py-2 leading-6`}
              />
            </div>
          </div>
        </Panel>

        <Panel
          title="Lesson timeline"
          description={`${totalMinutes} minutes. The tutors only work in phases you switch on, and you move the class on.`}
        >
          <ol role="list" className="space-y-2">
            {timeline.map((phase, i) => (
              <li key={i} className="grid grid-cols-[1fr_5.5rem] items-center gap-2 sm:grid-cols-[1fr_6rem_8rem_auto]">
                <input
                  aria-label={`Phase ${i + 1} name`}
                  required
                  value={phase.name}
                  onChange={(e) => patchPhase(i, { name: e.target.value })}
                  className={field}
                />
                <label className="flex items-center gap-1.5 text-sm text-pencil">
                  <input
                    aria-label={`Phase ${i + 1} minutes`}
                    type="number"
                    min={1}
                    max={240}
                    required
                    value={phase.minutes}
                    onChange={(e) => patchPhase(i, { minutes: Number(e.target.value) })}
                    className={`${field} w-16 px-2 text-right`}
                  />
                  min
                </label>
                <label className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={phase.tutors_on}
                    onChange={(e) => patchPhase(i, { tutors_on: e.target.checked })}
                  />
                  Tutors on
                </label>
                {timeline.length > 1 ? (
                  <button
                    type="button"
                    className={removeLink}
                    onClick={() => setTimeline((all) => all.filter((_, j) => j !== i))}
                  >
                    remove
                  </button>
                ) : (
                  <span />
                )}
              </li>
            ))}
          </ol>
          {!hasTutorPhase && (
            <p className="mt-2 text-sm text-amber">Switch tutors on in at least one phase, or students can&apos;t get help.</p>
          )}
          <Button
            type="button"
            variant="quiet"
            size="sm"
            className="mt-3"
            onClick={() => setTimeline((all) => [...all, { name: "", minutes: 10, tutors_on: false }])}
          >
            Add a phase
          </Button>
        </Panel>

        <Panel title="How much help is allowed">
          <fieldset>
            <legend className="mb-2 text-sm text-pencil">
              Help moves up one step only after the student has tried, and stops here.
            </legend>
            <div className="space-y-1.5">
              {HINTABLE_RUNGS.map((rung) => (
                <label key={rung} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="maxRung"
                    value={rung}
                    checked={maxRung === rung}
                    onChange={() => {
                      setMaxRung(rung);
                      if (rung !== "full_solution") setAllowFull(false);
                    }}
                  />
                  <span className="text-ink">Up to {RUNG_LABEL[rung]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {maxRung === "full_solution" && (
            <label className="mt-3 flex items-start gap-2 rounded-[var(--radius-control)] border border-amber/25 bg-amber-wash px-3 py-2 text-sm">
              <input type="checkbox" checked={allowFull} onChange={(e) => setAllowFull(e.target.checked)} className="mt-0.5" />
              <span className="text-ink">
                Yes, the tutor may give the whole answer. Unrestricted help has been found to improve
                practice while harming later unaided work, so this needs saying explicitly.
              </span>
            </label>
          )}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="repeat" className={label}>
                Tell me when a student is stuck this many times
              </label>
              <input
                id="repeat"
                type="number"
                min={1}
                max={20}
                value={repeatedIncorrect}
                onChange={(e) => setRepeatedIncorrect(Number(e.target.value))}
                className={field}
              />
            </div>
            <div>
              <label htmlFor="floor" className={label}>
                Send them to me if the tutor is less sure than
              </label>
              <input
                id="floor"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={confidenceFloor}
                onChange={(e) => setConfidenceFloor(Number(e.target.value))}
                className={field}
              />
            </div>
          </div>
        </Panel>

        {items.map((item, index) => (
          <TaskPanel
            key={index}
            index={index}
            item={item}
            maxRung={maxRung}
            canRemove={items.length > 1}
            onPatch={(patch) => patchItem(index, patch)}
            onKind={(kind) =>
              patchItem(index, {
                kind,
                expected_answer: kind === "short_answer" ? item.expected_answer ?? "" : null,
                rubric:
                  kind === "written_response"
                    ? item.rubric ?? { criteria: DEFAULT_RUBRIC.map((c) => ({ ...c })) }
                    : null,
              })
            }
            onRemove={() => setItems((all) => all.filter((_, i) => i !== index))}
          />
        ))}

        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="quiet" onClick={() => setItems((all) => [...all, emptyItem()])}>
            Add a one-line question
          </Button>
          <Button
            type="button"
            variant="quiet"
            onClick={() => setItems((all) => [...all, emptyItem("written_response")])}
          >
            Add a writing task
          </Button>
        </div>

        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-between gap-3 border-t border-rule bg-paper/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-[var(--radius-sheet)] sm:border">
          <span className="text-sm text-pencil" aria-live="polite">
            {savedAt ? `Draft saved at ${savedAt}` : "Saving keeps it as a draft. It governs nobody until approved."}
          </span>
          <div className="flex gap-2">
            <Link
              href="/teacher/contracts"
              className="inline-flex h-10 items-center px-2 text-sm text-pencil underline underline-offset-4 hover:text-ink"
            >
              Back to plans
            </Link>
            <Button type="submit" variant="quiet" disabled={busy !== null}>
              {busy === "save" ? "Saving…" : "Save draft"}
            </Button>
            <Button type="button" onClick={() => save(true)} disabled={busy !== null || !hasTutorPhase}>
              {busy === "approve" ? "Approving…" : "Save and approve"}
            </Button>
          </div>
        </div>
      </form>
    </>
  );
}

function TaskPanel({
  index,
  item,
  maxRung,
  canRemove,
  onPatch,
  onKind,
  onRemove,
}: {
  index: number;
  item: ItemIn;
  maxRung: Rung;
  canRemove: boolean;
  onPatch: (patch: Partial<ItemIn>) => void;
  onKind: (kind: ItemKind) => void;
  onRemove: () => void;
}) {
  const writing = item.kind === "written_response";
  const criteria = item.rubric?.criteria ?? [];
  const setCriteria = (next: Criterion[]) => onPatch({ rubric: { criteria: next } });
  const outOf = criteria.reduce((n, c) => n + (Number(c.max) || 0), 0);

  return (
    <Panel
      title={`Task ${index + 1}`}
      aside={
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-pencil">
            <span className="sr-only">Task {index + 1} type</span>
            <select
              value={item.kind ?? "short_answer"}
              onChange={(e) => onKind(e.target.value as ItemKind)}
              className={`${field} h-8 w-auto`}
            >
              <option value="short_answer">One-line answer</option>
              <option value="written_response">Writing task</option>
            </select>
          </label>
          {canRemove && (
            <button type="button" onClick={onRemove} className={removeLink}>
              remove
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {writing ? (
          <div>
            <label htmlFor={`prompt-${index}`} className={label}>
              What students write
            </label>
            <textarea
              id={`prompt-${index}`}
              required
              rows={2}
              value={item.prompt}
              onChange={(e) => onPatch({ prompt: e.target.value })}
              placeholder="Write one paragraph that presents and supports one criterion for choosing a profession."
              className={`${field} h-auto py-2 leading-6`}
            />
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
            <div>
              <label htmlFor={`prompt-${index}`} className={label}>
                Question
              </label>
              <input
                id={`prompt-${index}`}
                required
                value={item.prompt}
                onChange={(e) => onPatch({ prompt: e.target.value })}
                placeholder="What is the unit of force?"
                className={field}
              />
            </div>
            <div>
              <label htmlFor={`answer-${index}`} className={label}>
                Answer
              </label>
              <input
                id={`answer-${index}`}
                required
                value={item.expected_answer ?? ""}
                onChange={(e) => onPatch({ expected_answer: e.target.value })}
                placeholder="newton"
                className={field}
              />
              <p className="mt-1 text-xs text-faint">Marked here, never by the model.</p>
            </div>
          </div>
        )}

        {writing && (
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-ink">Rubric, out of {outOf}</legend>
            <p className="mb-2 text-xs text-faint">
              The tutor suggests a score against this. You confirm it before the student sees it.
            </p>
            <div className="space-y-2">
              {criteria.map((c, ci) => (
                <div key={ci} className="grid gap-2 sm:grid-cols-[9rem_4.5rem_1fr_auto] sm:items-start">
                  <input
                    aria-label={`Rubric area ${ci + 1}`}
                    required
                    value={c.name}
                    onChange={(e) => setCriteria(criteria.map((x, j) => (j === ci ? { ...x, name: e.target.value } : x)))}
                    placeholder="Content"
                    className={field}
                  />
                  <input
                    aria-label={`Points for ${c.name || `area ${ci + 1}`}`}
                    type="number"
                    min={1}
                    max={20}
                    required
                    value={c.max}
                    onChange={(e) => setCriteria(criteria.map((x, j) => (j === ci ? { ...x, max: Number(e.target.value) } : x)))}
                    className={`${field} text-right`}
                  />
                  <input
                    aria-label={`What full marks looks like for ${c.name || `area ${ci + 1}`}`}
                    value={c.description ?? ""}
                    onChange={(e) =>
                      setCriteria(criteria.map((x, j) => (j === ci ? { ...x, description: e.target.value } : x)))
                    }
                    placeholder="What full marks looks like"
                    className={field}
                  />
                  {criteria.length > 1 ? (
                    <button
                      type="button"
                      className={`${removeLink} sm:mt-3`}
                      onClick={() => setCriteria(criteria.filter((_, j) => j !== ci))}
                    >
                      remove
                    </button>
                  ) : (
                    <span />
                  )}
                </div>
              ))}
            </div>
            {criteria.length < 8 && (
              <Button
                type="button"
                variant="quiet"
                size="sm"
                className="mt-2"
                onClick={() => setCriteria([...criteria, { name: "", max: 2, description: "" }])}
              >
                Add a rubric area
              </Button>
            )}
          </fieldset>
        )}

        <fieldset>
          <legend className="mb-1 text-sm font-medium text-ink">Your wording for each step of help</legend>
          <p className="mb-2 text-xs text-faint">
            The tutor uses your line for the step it has reached. Leave one blank and it uses a short
            general prompt.
          </p>
          <div className="space-y-2">
            {HINTABLE_RUNGS.filter((r) => HINTABLE_RUNGS.indexOf(r) <= HINTABLE_RUNGS.indexOf(maxRung)).map((rung) => (
              <div key={rung} className="grid gap-1 sm:grid-cols-[10rem_1fr] sm:items-center">
                <label htmlFor={`${rung}-${index}`} className="text-xs text-pencil sm:text-right">
                  {RUNG_LABEL[rung]}
                </label>
                <input
                  id={`${rung}-${index}`}
                  value={item.hint_templates[rung] ?? ""}
                  onChange={(e) => onPatch({ hint_templates: { ...item.hint_templates, [rung]: e.target.value } })}
                  className={field}
                />
              </div>
            ))}
          </div>
        </fieldset>

        {!writing && (
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-ink">Mistakes it may name</legend>
            <p className="mb-2 text-xs text-faint">
              A closed list. The tutor cannot invent a diagnosis outside it, which is what makes what it
              tells you checkable.
            </p>
            <div className="space-y-2">
              {item.misconception_vocabulary.map((m, mi) => (
                <div key={mi} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
                  <input
                    aria-label={`Code for mistake ${mi + 1}`}
                    value={m.code}
                    onChange={(e) =>
                      onPatch({
                        misconception_vocabulary: item.misconception_vocabulary.map((x, j) =>
                          j === mi ? { ...x, code: e.target.value } : x,
                        ),
                      })
                    }
                    placeholder="confuses_mass_and_weight"
                    className={field}
                  />
                  <input
                    aria-label={`Description of mistake ${mi + 1}`}
                    value={m.label}
                    onChange={(e) =>
                      onPatch({
                        misconception_vocabulary: item.misconception_vocabulary.map((x, j) =>
                          j === mi ? { ...x, label: e.target.value } : x,
                        ),
                      })
                    }
                    placeholder="Treats mass and weight as the same thing"
                    className={field}
                  />
                  <button
                    type="button"
                    onClick={() =>
                      onPatch({ misconception_vocabulary: item.misconception_vocabulary.filter((_, j) => j !== mi) })
                    }
                    className={removeLink}
                  >
                    remove
                  </button>
                </div>
              ))}
            </div>
            <Button
              type="button"
              variant="quiet"
              size="sm"
              className="mt-2"
              onClick={() =>
                onPatch({ misconception_vocabulary: [...item.misconception_vocabulary, { code: "", label: "" }] })
              }
            >
              Add a mistake
            </Button>
          </fieldset>
        )}
      </div>
    </Panel>
  );
}
