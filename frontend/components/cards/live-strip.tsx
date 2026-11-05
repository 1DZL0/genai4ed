import type { StripRow } from "@/lib/api";

/* ---------- the one pill beside "All my lessons" ---------- */

export type AttentionState = "needs_you" | "struggling" | "finished";

export type Attention = {
  /** The states present, most urgent first: one dot each, never one per student. Empty
   * when a class is running and nobody needs anything. */
  states: AttentionState[];
  words: string;
  /** Pressing it shows the class: the most urgent one when several are running. */
  action: { action: "show_class"; session_id: string };
};

/** One short pill for the running classes, with a dot for each colour present: red when
 * someone needs the teacher, amber when someone is struggling, green when someone has
 * finished; with nothing to flag, just the class's name, as the way back to its board. The
 * class whose board is on screen is left out: its tiles already say it all. */
export function needsAttention(rows: StripRow[], boardSession: string | null): Attention | null {
  const away = rows.filter((r) => r.session_id !== boardSession);
  if (away.length === 0) return null;
  const red = away.filter((r) => r.needs_you.length + r.needs_you_more > 0);
  const amber = away.filter((r) => (r.struggling ?? []).length > 0);
  const green = away.filter((r) => (r.finished ?? []).length > 0);
  const states: AttentionState[] = [];
  if (red.length) states.push("needs_you");
  if (amber.length) states.push("struggling");
  if (green.length) states.push("finished");
  const first = red[0] ?? amber[0] ?? green[0] ?? away[0];
  const words =
    states[0] === "needs_you"
      ? "You're needed"
      : states[0] === "struggling"
        ? "Someone is struggling"
        : states[0] === "finished"
          ? "Someone has finished"
          : `${first.class_label} is running`;
  return { states, words, action: { action: "show_class", session_id: first.session_id } };
}
