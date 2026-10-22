"use client";

import { useState } from "react";
import { ApiError, researchApi, type ResearchTurn } from "@/lib/api";
import { Button, Empty, ErrorNote } from "@/components/ui";

type Reply = Record<string, unknown>;

const PRE =
  "mt-2 max-h-80 overflow-auto rounded-[var(--radius-control)] bg-sunken p-3 text-xs whitespace-pre-wrap text-ink";

/** Every model call of one lesson run (or the teachers' conversations), opened on demand. */
export function ResearchTurns({
  researchKey,
  sessionId,
  label,
}: {
  researchKey: string;
  sessionId?: string;
  label: string;
}) {
  const [turns, setTurns] = useState<ResearchTurn[] | null>(null);
  const [who, setWho] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setTurns((await researchApi.turns(researchKey, sessionId)).turns);
    } catch (e) {
      setError((e as ApiError).message);
    }
    setBusy(false);
  }

  if (!turns) {
    return (
      <div className="mt-3 flex flex-col gap-2">
        <Button
          size="sm"
          variant="quiet"
          disabled={busy}
          onClick={load}
          className="self-start"
        >
          {busy ? "Opening…" : label}
        </Button>
        {error && <ErrorNote>{error}</ErrorNote>}
      </div>
    );
  }

  const people = [...new Set(turns.map(whoOf))];
  const shown = who ? turns.filter((t) => whoOf(t) === who) : turns;

  return (
    <div className="mt-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-pencil">
        <span>
          {turns.length} model call{turns.length === 1 ? "" : "s"}
        </span>
        {people.length > 1 && (
          <label className="flex items-center gap-2">
            Show
            <select
              value={who}
              onChange={(e) => setWho(e.target.value)}
              className="rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 py-1 text-ink"
            >
              <option value="">everyone</option>
              {people.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          onClick={() => setTurns(null)}
          className="text-pencil underline decoration-rule-strong underline-offset-4 hover:text-ink"
        >
          Close
        </button>
      </div>
      {shown.length === 0 && <Empty>No model calls here yet.</Empty>}
      <ol className="flex flex-col gap-3">
        {shown.map((t) => (
          <Turn key={t.id} turn={t} />
        ))}
      </ol>
    </div>
  );
}

function whoOf(t: ResearchTurn): string {
  if (t.mode === "teacher") return t.teacher ? `teacher ${t.teacher}` : "teacher";
  if (t.mode === "review") return "end of lesson review";
  return t.student ?? "student";
}

function Turn({ turn }: { turn: ResearchTurn }) {
  const reply: Reply =
    typeof turn.reply === "object" && turn.reply ? turn.reply : {};
  const text =
    (reply.message as string) ??
    (reply.reply as string) ??
    (reply.summary as string) ??
    (typeof turn.reply === "string" ? turn.reply : "");
  const asked =
    turn.said ??
    (turn.button ? `(pressed: ${turn.button.replaceAll("_", " ")})` : null) ??
    (turn.mode === "student" ? "(opened the lesson)" : null);
  const time = new Date(turn.at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <li className="rounded-[var(--radius-control)] border border-rule p-3 text-sm">
      <p className="text-xs text-pencil">
        {time} · <span className="font-semibold text-ink">{whoOf(turn)}</span> ·
        prompts {turn.prompts} · {turn.model} ·{" "}
        {(turn.latency_ms / 1000).toFixed(1)}s
      </p>

      {asked && (
        <p className="mt-2 text-ink">
          <span className="text-pencil">Said to the agent: </span>
          {asked}
        </p>
      )}
      {turn.error ? (
        <p className="mt-2 text-red-pen">No usable reply: {turn.error}</p>
      ) : (
        <p className="mt-2 whitespace-pre-line text-ink">
          <span className="text-pencil">Agent: </span>
          {text}
        </p>
      )}

      <Facts turn={turn} reply={reply} />

      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-semibold text-pencil hover:text-ink">
          What it was shown, and its full reply
        </summary>
        <p className="mt-2 text-xs text-pencil">
          The records the server put in front of the model for this call, by id.
        </p>
        <pre className={PRE}>{JSON.stringify(turn.shown, null, 2)}</pre>
        <p className="mt-2 text-xs text-pencil">
          The reply exactly as the model sent it.
        </p>
        <pre className={PRE}>
          {typeof turn.reply === "string"
            ? turn.reply
            : JSON.stringify(turn.reply, null, 2)}
        </pre>
      </details>
    </li>
  );
}

/** What the reply claimed and what the server checked, as short tags. */
function Facts({ turn, reply }: { turn: ResearchTurn; reply: Reply }) {
  const tags: { text: string; tone?: "warn" | "good" }[] = [];
  const shown = turn.shown as Record<string, unknown>;

  if (typeof shown.step_index === "number")
    tags.push({ text: `step ${shown.step_index + 1}` });
  if (shown.allowed_disclosure)
    tags.push({ text: `may give: ${shown.allowed_disclosure}` });
  if (reply.move) tags.push({ text: `move: ${reply.move}` });
  if (reply.disclosure)
    tags.push({ text: `says it gave: ${reply.disclosure}` });
  const judged = reply.assessment as Reply | null | undefined;
  if (judged?.judgment)
    tags.push({
      text: `judged: ${judged.judgment}`,
      tone: judged.judgment === "met" ? "good" : undefined,
    });
  if (reply.step_done) tags.push({ text: "moved on", tone: "good" });
  for (const s of (reply.signals as Reply[] | undefined) ?? [])
    tags.push({
      text: `noticed ${String(s.kind).replaceAll("_", " ")}${s.tell_teacher ? ", told the teacher" : ", noted only"}`,
      tone: s.tell_teacher ? "warn" : undefined,
    });
  if (Array.isArray(reply.do) && reply.do.length)
    tags.push({ text: `asked to do: ${reply.do.join(", ")}` });
  if (reply.show && reply.show !== "nothing")
    tags.push({ text: `showed: ${reply.show}` });
  if (reply.brief) tags.push({ text: "drafted a lesson" });
  if (turn.leakage && turn.leakage !== "skipped")
    tags.push({
      text: `answer check: ${turn.leakage}`,
      tone: turn.leakage === "passed" ? undefined : "warn",
    });
  for (const c of turn.conflicts)
    tags.push({ text: `check: ${c.replaceAll("_", " ")}`, tone: "warn" });
  if (turn.retried_because)
    tags.push({
      text: `first draft sent back: ${turn.retried_because.slice(0, 90)}`,
      tone: "warn",
    });
  if (turn.outcome !== "ok")
    tags.push({ text: `outcome: ${turn.outcome}`, tone: "warn" });

  const look = {
    warn: "border-amber/40 bg-amber-wash text-ink",
    good: "border-tick/30 bg-tick-wash text-ink",
    none: "border-rule bg-sheet text-pencil",
  };
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5 text-xs">
      {tags.map((t, i) => (
        <li
          key={i}
          className={`rounded-full border px-2 py-0.5 ${look[t.tone ?? "none"]}`}
        >
          {t.text}
        </li>
      ))}
    </ul>
  );
}
