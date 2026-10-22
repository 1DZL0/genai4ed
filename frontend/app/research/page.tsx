"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ApiError, researchApi, type Instructions } from "@/lib/api";
import { inputClass } from "@/components/auth-layout";
import { Button, ErrorNote, Skeleton } from "@/components/ui";
import { ConversationView, LessonView, Overview } from "@/components/research-view";
import { Shell } from "@/components/app-header";
import { useMe } from "@/lib/session";

/** The research view: the whole study, one lesson, or one conversation, chosen by the address
 * (`?lesson=` and `&student=`) so any of them can be linked to. */
export default function ResearchPage() {
  return (
    <Suspense fallback={null}>
      <Research />
    </Suspense>
  );
}

function Research() {
  // Signed in as a teacher, the page opens without a key. A student is never sent any of it,
  // so a student's page does not even ask, unless a researcher in that browser gives the key.
  const me = useMe();
  const params = useSearchParams();
  const lessonId = params.get("lesson");
  const studentId = params.get("student");
  const [typed, setTyped] = useState("");
  const [key, setKey] = useState("");
  const student = me?.role === "student";
  const allowed = Boolean(key) || (Boolean(me) && !student);

  const overview = useSWR(allowed && !lessonId ? ["research", key] : null, () =>
    researchApi.summary(key),
  );
  const lesson = useSWR(allowed && lessonId && !studentId ? ["research-lesson", lessonId, key] : null, () =>
    researchApi.lesson(key, lessonId!),
  );
  const conversation = useSWR(
    allowed && lessonId && studentId ? ["research-conversation", lessonId, studentId, key] : null,
    () => researchApi.conversation(key, lessonId!, studentId!),
  );
  const error = (overview.error ?? lesson.error ?? conversation.error) as ApiError | undefined;
  const loading = overview.isLoading || lesson.isLoading || conversation.isLoading;

  if (me === undefined) return null;

  return (
    <Shell me={me}>
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 sm:px-6">
        {student && !key && (
          <p className="text-base text-ink">
            The research view is for teachers and researchers. Your own lessons are under Lessons.
            A researcher signed in here as a student can still open it with the research key.
          </p>
        )}
        {(me === null || (student && !key)) && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setKey(typed);
            }}
            className="flex flex-wrap items-end gap-3"
          >
            <label className="flex flex-col gap-1 text-sm text-ink">
              Research key
              <input
                type="password"
                autoComplete="off"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                className={inputClass}
              />
            </label>
            <Button type="submit" disabled={!typed}>
              Open
            </Button>
          </form>
        )}
        {error && (
          <ErrorNote>
            {error.status === 404 && (!me || student)
              ? "That key was not accepted, or no research key is set on the server."
              : error.message}
          </ErrorNote>
        )}
        {loading && <Skeleton label="Reading the records" rows={4} />}

        {conversation.data && <ConversationView data={conversation.data} />}
        {!studentId && lesson.data && <LessonView data={lesson.data} researchKey={key} />}
        {!lessonId && overview.data && (
          <Overview
            data={overview.data}
            researchKey={key}
            settings={<Settings data={overview.data} researchKey={key} />}
          />
        )}
      </main>
    </Shell>
  );
}

/** Study settings, the downloads and the agent's instructions, in one small box. */
function Settings({
  data,
  researchKey,
}: {
  data: Awaited<ReturnType<typeof researchApi.summary>>;
  researchKey: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [told, setTold] = useState<Instructions | null>(null);

  async function tryTo(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError((e as ApiError).message);
    }
    setBusy(false);
  }

  return (
    <div className="flex min-w-[18rem] flex-col gap-2 rounded-[var(--radius-sheet)] border border-rule bg-sheet px-4 py-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5">
        <dt className="text-pencil">Model</dt>
        <dd className="font-semibold text-ink">{data.study.model}</dd>
        <dt className="text-pencil">Prompts</dt>
        <dd className="font-semibold text-ink">{data.study.prompt_versions.join(", ") || "none yet"}</dd>
        <dt className="text-pencil">Rule checks</dt>
        <dd className="font-semibold text-ink">{data.study.supervisor ? "Enforced" : "Recorded, not enforced"}</dd>
        <dt className="text-pencil">Study</dt>
        <dd className="font-semibold text-ink">
          {data.study.active ? `Running (${data.study.policy})` : "Not running"}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-2 border-t border-rule pt-2">
        <Button size="sm" variant="quiet" disabled={busy} onClick={() => tryTo(() => researchApi.download(researchKey, false))}>
          Download the records (CSV)
        </Button>
        <Button size="sm" variant="quiet" disabled={busy} onClick={() => tryTo(() => researchApi.download(researchKey, true))}>
          With what was written
        </Button>
        {!told && (
          <Button size="sm" variant="quiet" disabled={busy} onClick={() => tryTo(async () => setTold(await researchApi.instructions(researchKey)))}>
            What the agent is told
          </Button>
        )}
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {told && (
        <div className="max-w-xl space-y-2 border-t border-rule pt-2">
          {(["teacher", "student", "review"] as const).map((part) => (
            <details key={part}>
              <summary className="cursor-pointer font-semibold text-ink">
                {part === "teacher" ? "Talking to the teacher" : part === "student" ? "Teaching a student" : "Suggesting outcomes"}
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink">
                {told[part]}
              </pre>
            </details>
          ))}
          {told.approaches && (
            <p className="text-xs text-pencil">
              Teaching approaches, version {told.approaches.version}. Held constant in both: {told.approaches.held_constant}
            </p>
          )}
          {Object.entries(told.approaches?.items ?? {}).map(([key, a]) => (
            <details key={key}>
              <summary className="cursor-pointer font-semibold text-ink">
                Teaching approach: {a.name}
              </summary>
              <p className="mt-2 text-xs text-pencil">While drafting with the teacher:</p>
              <pre className="mt-1 max-h-60 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink">
                {a.drafting}
              </pre>
              <p className="mt-2 text-xs text-pencil">On every turn with a student:</p>
              <pre className="mt-1 max-h-60 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink">
                {a.teaching}
              </pre>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
