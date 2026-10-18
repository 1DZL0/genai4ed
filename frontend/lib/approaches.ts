/** The two teaching approaches a lesson can be taught by, for a side-by-side comparison. What
 * the agent is told for each lives on the server; this is only how they are named on screen. */
export const APPROACHES = {
  direct: {
    name: "Direct instruction",
    short: "Explain first, then questions with definite answers, corrected at once.",
  },
  inquiry: {
    name: "Guided inquiry",
    short: "Problem first, hints only, the student explains before the agent does.",
  },
} as const;

export type ApproachKey = keyof typeof APPROACHES;

export function approachName(key: string | null | undefined): string | null {
  return key && key in APPROACHES ? APPROACHES[key as ApproachKey].name : null;
}
