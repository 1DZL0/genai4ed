"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  HINTABLE_RUNGS,
  type ClassOut,
  type ContractIn,
  type ItemIn,
  type Rung,
} from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Button, ErrorNote, Panel } from "@/components/ui";

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
  attempt: "no help — they work alone",
  diagnostic_question: "a diagnostic question",
  conceptual_cue: "a conceptual cue",
  targeted_hint: "a targeted hint",
  analogous_example: "an analogous example",
  partial_step: "a partial step",
  full_solution: "the full solution",
};

function emptyItem(): ItemIn {
  return {
    prompt: "",
    expected_answer: "",
    hint_templates: {},
    misconception_vocabulary: [],
  };
}

export default function NewContract() {
  const router = useRouter();
  const me = useSignedIn("teacher");

  const [classes, setClasses] = useState<ClassOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState<string>("mathematics");
  const [objectiveCode, setObjectiveCode] = useState("");
  const [classId, setClassId] = useState("");
  const [notes, setNotes] = useState("");
  const [maxRung, setMaxRung] = useState<Rung>("partial_step");
  const [allowFull, setAllowFull] = useState(false);
  const [repeatedIncorrect, setRepeatedIncorrect] = useState(3);
  const [confidenceFloor, setConfidenceFloor] = useState(0.45);
  const [items, setItems] = useState<ItemIn[]>([emptyItem()]);

  useEffect(() => {
    if (!me) return;
    api
      .classes()
      .then((rows) => {
        setClasses(rows);
        setClassId((current) => current || (rows[0]?.id ?? ""));
      })
      .catch(() => setError("Could not load your classes."));
  }, [me]);

  function patchItem(index: number, patch: Partial<ItemIn>) {
    setItems((all) => all.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);

    const body: ContractIn = {
      title,
      subject,
      objective_code: objectiveCode,
      objective_title: title,
      class_id: classId,
      max_rung: maxRung,
      allow_full_solution: allowFull,
      repeated_incorrect: repeatedIncorrect,
      repeated_misconception: 2,
      confidence_floor: confidenceFloor,
      notes,
      items,
    };

    try {
      const contract = await api.createContract(body);
      router.push(`/teacher/contracts`);
      return contract;
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (!me) return null;

  const field =
    "block h-10 w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none";

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <PageTitle lede="The tutor can only use what you write here, and never goes past the limit you set. It doesn't make up questions, hints or diagnoses.">
          Write a lesson
        </PageTitle>

        {error && (
          <div className="mb-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        <form onSubmit={save} className="space-y-5">
          <Panel title="The lesson">
            <div className="space-y-3">
              <div>
                <label htmlFor="title" className="mb-1 block text-sm font-medium text-ink">
                  Title
                </label>
                <input
                  id="title"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Forces and motion"
                  className={field}
                />
              </div>

              <div>
                <label htmlFor="subject" className="mb-1 block text-sm font-medium text-ink">
                  Subject
                </label>
                <select
                  id="subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className={field}
                >
                  {SUBJECTS.map((s) => (
                    <option key={s} value={s}>
                      {s.charAt(0).toUpperCase() + s.slice(1)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="code" className="mb-1 block text-sm font-medium text-ink">
                    Objective code
                  </label>
                  <input
                    id="code"
                    required
                    value={objectiveCode}
                    onChange={(e) => setObjectiveCode(e.target.value)}
                    placeholder="SCI-FORCES-1"
                    className={field}
                  />
                  <p className="mt-1 text-xs text-faint">
                    How a student&apos;s past work on this skill is found later.
                  </p>
                </div>
                <div>
                  <label htmlFor="klass" className="mb-1 block text-sm font-medium text-ink">
                    Class
                  </label>
                  <select
                    id="klass"
                    required
                    value={classId}
                    onChange={(e) => setClassId(e.target.value)}
                    className={field}
                  >
                    {classes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label} ({c.students} students)
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label htmlFor="notes" className="mb-1 block text-sm font-medium text-ink">
                  Note to the class <span className="font-normal text-faint">(optional)</span>
                </label>
                <input
                  id="notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="We did the experiment together first."
                  className={field}
                />
              </div>
            </div>
          </Panel>

          <Panel title="How much help is allowed">
            <fieldset>
              <legend className="mb-2 text-sm text-pencil">
                The tutor climbs one rung per wrong answer and stops here.
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
                <input
                  type="checkbox"
                  checked={allowFull}
                  onChange={(e) => setAllowFull(e.target.checked)}
                  className="mt-0.5"
                />
                <span className="text-ink">
                  Yes, the tutor may give the whole answer. Unrestricted help has been found to
                  improve practice while harming later unaided work, so this needs saying
                  explicitly.
                </span>
              </label>
            )}

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="repeat" className="mb-1 block text-sm font-medium text-ink">
                  Tell me after this many wrong answers
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
                <label htmlFor="floor" className="mb-1 block text-sm font-medium text-ink">
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
            <Panel
              key={index}
              title={`Question ${index + 1}`}
              aside={
                items.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => setItems((all) => all.filter((_, i) => i !== index))}
                    className="text-xs text-pencil underline underline-offset-2 hover:text-red-pen"
                  >
                    remove
                  </button>
                ) : undefined
              }
            >
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                  <div>
                    <label
                      htmlFor={`prompt-${index}`}
                      className="mb-1 block text-sm font-medium text-ink"
                    >
                      Question
                    </label>
                    <input
                      id={`prompt-${index}`}
                      required
                      value={item.prompt}
                      onChange={(e) => patchItem(index, { prompt: e.target.value })}
                      placeholder="What is the unit of force?"
                      className={field}
                    />
                  </div>
                  <div>
                    <label
                      htmlFor={`answer-${index}`}
                      className="mb-1 block text-sm font-medium text-ink"
                    >
                      Answer
                    </label>
                    <input
                      id={`answer-${index}`}
                      required
                      value={item.expected_answer}
                      onChange={(e) => patchItem(index, { expected_answer: e.target.value })}
                      placeholder="newton"
                      className={field}
                    />
                    <p className="mt-1 text-xs text-faint">Marked here, never by the model.</p>
                  </div>
                </div>

                <fieldset>
                  <legend className="mb-1 text-sm font-medium text-ink">Your wording</legend>
                  <p className="mb-2 text-xs text-faint">
                    The tutor is given only the line for the rung it has reached. Leave a rung
                    blank and it falls back to a generic nudge.
                  </p>
                  <div className="space-y-2">
                    {HINTABLE_RUNGS.filter(
                      (r) => HINTABLE_RUNGS.indexOf(r) <= HINTABLE_RUNGS.indexOf(maxRung),
                    ).map((rung) => (
                      <div key={rung} className="grid gap-1 sm:grid-cols-[10rem_1fr] sm:items-center">
                        <label
                          htmlFor={`${rung}-${index}`}
                          className="text-xs text-pencil sm:text-right"
                        >
                          {RUNG_LABEL[rung]}
                        </label>
                        <input
                          id={`${rung}-${index}`}
                          value={item.hint_templates[rung] ?? ""}
                          onChange={(e) =>
                            patchItem(index, {
                              hint_templates: {
                                ...item.hint_templates,
                                [rung]: e.target.value,
                              },
                            })
                          }
                          className={field}
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>

                <fieldset>
                  <legend className="mb-1 text-sm font-medium text-ink">
                    Mistakes it may name
                  </legend>
                  <p className="mb-2 text-xs text-faint">
                    A closed list. The tutor cannot invent a diagnosis outside it, which is what
                    makes what it tells you checkable.
                  </p>
                  <div className="space-y-2">
                    {item.misconception_vocabulary.map((m, mi) => (
                      <div key={mi} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
                        <input
                          aria-label={`Code for mistake ${mi + 1}`}
                          value={m.code}
                          onChange={(e) =>
                            patchItem(index, {
                              misconception_vocabulary: item.misconception_vocabulary.map(
                                (x, j) => (j === mi ? { ...x, code: e.target.value } : x),
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
                            patchItem(index, {
                              misconception_vocabulary: item.misconception_vocabulary.map(
                                (x, j) => (j === mi ? { ...x, label: e.target.value } : x),
                              ),
                            })
                          }
                          placeholder="Treats mass and weight as the same thing"
                          className={field}
                        />
                        <button
                          type="button"
                          onClick={() =>
                            patchItem(index, {
                              misconception_vocabulary: item.misconception_vocabulary.filter(
                                (_, j) => j !== mi,
                              ),
                            })
                          }
                          className="text-xs text-pencil underline underline-offset-2 hover:text-red-pen"
                        >
                          remove
                        </button>
                      </div>
                    ))}
                  </div>
                  <Button
                    type="button"
                    variant="quiet"
                    className="mt-2"
                    onClick={() =>
                      patchItem(index, {
                        misconception_vocabulary: [
                          ...item.misconception_vocabulary,
                          { code: "", label: "" },
                        ],
                      })
                    }
                  >
                    Add a mistake
                  </Button>
                </fieldset>
              </div>
            </Panel>
          ))}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              type="button"
              variant="quiet"
              onClick={() => setItems((all) => [...all, emptyItem()])}
            >
              Add a question
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save as draft"}
            </Button>
          </div>

          <p className="text-xs text-faint">
            Saving creates a draft. It governs nobody until you read it back and activate it.
          </p>
        </form>
      </main>
    </>
  );
}
