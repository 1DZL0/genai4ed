"use client";

import type { Design } from "@/lib/api";
import { SubjectName } from "@/components/ui";

const STEP_KIND: Record<string, string> = {
  explain: "Explain",
  question: "Question",
  practice: "Practice",
  check: "Check",
};

/**
 * The lesson brief as a document the teacher reads, not a form they fill in.
 * Everything here is changed by talking to the agent.
 */
export function LessonBriefView({ design }: { design: Design }) {
  const { brief } = design;
  const started = brief.steps.length > 0 || brief.objectives.length > 0;

  if (!started) {
    return (
      <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-6 py-10 text-center">
        <p className="font-serif text-lg font-semibold text-ink">The lesson brief appears here</p>
        <p className="mx-auto mt-2 max-w-sm text-sm text-pencil">
          Tell the agent what you want to teach, who it&apos;s for and how long you have. Attach
          slides, a worksheet or notes if you have them.
        </p>
      </div>
    );
  }

  return (
    <article className="rounded-[var(--radius-sheet)] border border-rule bg-sheet">
      <header className="border-b border-rule px-6 pt-5 pb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {brief.subject && <SubjectName subject={brief.subject} />}
          <span className="figures text-pencil">{brief.duration_minutes} minutes</span>
          {brief.year_group && <span className="text-pencil">{brief.year_group}</span>}
        </div>
        <h2 className="mt-1 font-serif text-xl font-semibold text-ink">
          {brief.title || "Untitled lesson"}
        </h2>
        {brief.prior_knowledge && (
          <p className="mt-1 text-sm text-pencil">Builds on: {brief.prior_knowledge}</p>
        )}
      </header>

      <Section title="Students will">
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
          {brief.objectives.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      </Section>

      <Section title="How the agent runs it">
        {brief.strategy && <p className="mb-3 text-sm text-pencil">{brief.strategy}</p>}
        <ol className="space-y-3">
          {brief.steps.map((step, i) => (
            <li key={`${step.name}-${i}`} className="flex gap-3">
              <span className="figures mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-bold text-ink">
                {i + 1}
              </span>
              <div className="min-w-0 text-sm">
                <p className="font-semibold text-ink">
                  {step.name}{" "}
                  <span className="font-normal text-faint">· {STEP_KIND[step.kind] ?? step.kind}</span>
                </p>
                <p className="text-ink">{step.goal}</p>
                {step.success_criteria.length > 0 && (
                  <p className="mt-0.5 text-pencil">
                    Done when: {step.success_criteria.join("; ")}
                  </p>
                )}
                {step.reference_answer && (
                  <p className="mt-0.5 text-faint">Answer (agent only): {step.reference_answer}</p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Rules for the agent">
        {brief.rules_text && (
          <p className="mb-2 text-sm text-ink">
            <span className="text-pencil">You said: </span>&ldquo;{brief.rules_text}&rdquo;
          </p>
        )}
        <ul className="space-y-1 text-sm text-ink">
          {design.rules_in_words.map((line) => (
            <li key={line} className="flex gap-2">
              <span aria-hidden className="text-faint">
                –
              </span>
              {line}
            </li>
          ))}
        </ul>
      </Section>

      {brief.assessment.length > 0 && (
        <Section title="How learning is judged">
          <ul className="space-y-1 text-sm">
            {brief.assessment.map((c) => (
              <li key={c.name}>
                <span className="font-semibold text-ink">{c.name}</span>{" "}
                <span className="figures text-pencil">({c.max})</span>
                {c.description && <span className="text-pencil"> · {c.description}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-faint">
            The agent suggests an outcome for each student. You confirm it before they see it.
          </p>
        </Section>
      )}

      {design.materials.length > 0 && (
        <Section title="Material the agent teaches from">
          <ul className="space-y-1 text-sm">
            {design.materials.map((m) => (
              <li key={m.id} className="flex flex-wrap gap-x-2">
                <span className="text-ink">{m.filename}</span>
                {!m.readable && (
                  <span className="text-amber">No text found (a scanned file can&apos;t be read yet)</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-rule px-6 py-4 last:border-b-0">
      <h3 className="mb-2 text-sm font-bold text-ink">{title}</h3>
      {children}
    </section>
  );
}
