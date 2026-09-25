"use client";

import type { ThreadCard } from "@/lib/api";
import type { Act } from "@/components/cards/parts";
import { ClassBoard } from "@/components/cards/class-board";
import { Lesson } from "@/components/cards/lesson";
import { Lessons } from "@/components/cards/lesson-row";
import { Outcomes } from "@/components/cards/outcomes";
import { Student } from "@/components/cards/student";

export type { Act } from "@/components/cards/parts";
export { LessonRow } from "@/components/cards/lesson-row";
export { LiveStrip } from "@/components/cards/live-strip";

/** The card the teacher is looking at. The server built it from records; every button is the teacher's action, never the agent's. */
export function ThreadCardView({ card, act, busy }: { card: ThreadCard; act: Act; busy: boolean }) {
  switch (card.type) {
    case "lesson":
      return <Lesson card={card} act={act} busy={busy} />;
    case "lessons":
      return <Lessons card={card} act={act} busy={busy} />;
    case "class":
      return <ClassBoard card={card} act={act} busy={busy} />;
    case "student":
      return <Student card={card} act={act} busy={busy} />;
    case "outcomes":
      return <Outcomes card={card} act={act} busy={busy} />;
  }
}
