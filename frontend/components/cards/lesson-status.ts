import type { LessonsCard } from "@/lib/api";

type Listed = LessonsCard["lessons"][number];

/** One word for where a lesson is, the same in the sidebar and the lessons panel, with the
 * colours of its pill: blue running, amber waiting on the teacher, green taught. */
export function lessonStatus(lesson: Listed): [string, string] {
  const waiting = "bg-amber-wash text-amber";
  if (lesson.live)
    return lesson.live.status === "paused"
      ? ["Paused", waiting]
      : ["Running", "bg-progress-wash text-progress"];
  // A change on top of an approved version: the approved one can still be started.
  if (lesson.status === "draft" && lesson.approved) return ["Change to approve", waiting];
  if (!lesson.ready) return ["Unfinished", waiting];
  if (lesson.last_run) return ["Taught", "bg-tick-wash text-tick"];
  if (lesson.status === "active") return ["Ready", "bg-sunken text-ink"];
  return ["Draft", waiting];
}

/** The pill a lesson's status sits in. */
export const STATUS_PILL = "rounded-full px-2 py-0.5 text-xs font-semibold";

/** What pressing Remove will do, said before it is done. */
export function removeWords(lesson: { live: unknown; last_run?: unknown; runs?: unknown[] }): string {
  if (lesson.live) return "Running now: removing it ends it for everyone.";
  if (lesson.last_run || (lesson.runs && lesson.runs.length > 0))
    return "Remove it? It leaves your list; its past lessons stay in Research.";
  return "Remove it?";
}

/** Whether Start can be pressed: an approved version exists, even under a change. Start runs
 * the approved version, so an unfinished change on top of it does not stop it. */
export function canStart(lesson: Listed): boolean {
  return lesson.status === "active" || lesson.approved;
}
