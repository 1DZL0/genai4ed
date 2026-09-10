"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  HINTABLE_RUNGS,
  type ContractIn,
  type ItemIn,
  type Rung,
} from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { NotIdentified } from "@/components/identify";
import { Button, DevBanner, ErrorNote, Panel } from "@/components/ui";

type ClassOut = { id: string; label: string; students: number };

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
  const who = useIdentity();

  const [classes, setClasses] = useState<ClassOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [objectiveCode, setObjectiveCode] = useState("");
  const [classId, setClassId] = useState("");
  const [notes, setNotes] = useState("");
  const [maxRung, setMaxRung] = useState<Rung>("partial_step");
  const [allowFull, setAllowFull] = useState(false);
  const [repeatedIncorrect, setRepeatedIncorrect] = useState(3);
  const [confidenceFloor, setConfidenceFloor] = useState(0.45);
  const [items, setItems] = useState<ItemIn[]>([emptyItem()]);

  useEffect(() => {
    if (!who) return;
    fetch(`${api.base}/api/teacher/classes`, {
      headers: { "X-GenAI4ED-Pseudonym": who },
    })
      .then((r) => r.json())
      .then((rows: ClassOut[]) => {
        setClasses(rows);
        setClassId((current) => current || (rows[0]?.id ?? ""));
      })
      .catch(() => setError("Could not load your classes."));
  }, [who]);

  function patchItem(index: number, patch: Partial<ItemIn>) {
    setItems((all) => all.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!who || busy) return;
    setBusy(true);
    setError(null);

    const body: ContractIn = {
      title,
      subject: "mathematics",
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
      const contract = await api.createContract(who, body);
      router.push(`/teacher/contracts`);
      return contract;
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (who === undefined) return null;
  if (who === null) return <NotIdentified />;

  const field =
    "w-full rounded border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint";

  return (
    <>
      <DevBanner who={who} onSwitch={() => router.push("/")} />
      <main className="mx-auto w-full max-w-3xl px-4 py-6">
        <h1 className="text-xl font-semibold text-ink">Write a lesson</h1>
        <p className="mt-1 mb-6 text-sm text-muted">
          The tutor can only say what you write here, and can never go further than the limit you
          set. It does not invent exercises, hints or diagnoses.
        </p>

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
                  placeholder="Linear equations — unknown on both sides"
                  className={field}
                />
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
                    placeholder="ALG-L4"
                    className={`${field} font-mono`}
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
                  placeholder="We did worked examples on the board first."
                  className={field}
                />
              </div>
            </div>
          </Panel>

          <Panel title="How much help is allowed">
            <fieldset>
              <legend className="mb-2 text-sm text-muted">
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
              <label className="mt-3 flex items-start gap-2 rounded border border-sev2/30 bg-sev2/5 px-3 py-2 text-sm">
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
                    className="text-xs text-muted underline underline-offset-2 hover:text-incorrect"
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
                      placeholder="Solve for x:  5x - 7 = 2x + 8"
                      className={`${field} font-mono`}
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
                      placeholder="5"
                      className={`${field} font-mono`}
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
                          className="text-xs text-muted sm:text-right"
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
                          placeholder="sign_error_on_transfer"
                          className={`${field} font-mono text-xs`}
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
                          placeholder="Moves a term without changing its sign"
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
                          className="text-xs text-muted underline underline-offset-2 hover:text-incorrect"
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
