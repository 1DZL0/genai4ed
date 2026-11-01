/** The little structure the agent may use beyond paragraphs, read out of plain text: a list, one
 * item per line starting with "- " or "1.", and a simple table, one row per line with | between
 * cells. Anything else is a paragraph, line breaks kept. No markup is interpreted. */

export type Block =
  | { kind: "p"; text: string }
  | { kind: "math"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[]; start: number }
  | { kind: "table"; head: string[]; rows: string[][] };

const BULLET = /^\s*[-*•]\s+/;
const NUMBER = /^\s*(\d+)[.)]\s+/;
const RULE = /^:?-{2,}:?$/;
const FRAMED = /^\s*\|.*\|\s*$/;

/** A line of working: an equals sign and mostly figures and signs, like 60 ÷ 10 = 6. */
export function isWorking(line: string): boolean {
  if (!line.includes("=") || line.length > 60) return false;
  const marks = line.replace(/\s/g, "");
  const letters = (marks.match(/[A-Za-z]/g) ?? []).length;
  return marks.length > 0 && letters <= marks.length * 0.3;
}

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

/** Lines that are a table: a |---| line under the header, or every row framed by pipes.
 * Lines that only contain pipes, such as |x| = 3 for an absolute value, stay as written. */
function isTable(lines: string[]): boolean {
  if (lines.length < 2 || !lines.every((l) => l.includes("|"))) return false;
  const separated = lines.some((l) => cells(l).every((c) => RULE.test(c)));
  return separated || lines.every((l) => FRAMED.test(l));
}

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of text.replace(/\r/g, "").split(/\n\s*\n/)) {
    const lines = chunk.split("\n").filter((l) => l.trim() !== "");
    if (lines.length === 0) continue;
    if (isTable(lines)) {
      const rows = lines.map(cells).filter((row) => !row.every((c) => RULE.test(c)));
      if (rows.length >= 2) {
        const [head, ...body] = rows;
        blocks.push({ kind: "table", head, rows: body });
        continue;
      }
    }
    // A chunk can mix a sentence, a list and a line of working: each run of a kind is
    // its own block, in order, so "That gives us a trick:" is a paragraph and the lines
    // under it are a list.
    for (const run of runs(lines)) {
      if (run.kind === "ul") {
        blocks.push({ kind: "ul", items: run.lines.map((l) => l.replace(BULLET, "")) });
      } else if (run.kind === "ol") {
        // A list that carries on after a paragraph keeps its numbers: 3, 4 stays 3, 4.
        const start = Number(run.lines[0].match(NUMBER)?.[1] ?? 1);
        blocks.push({ kind: "ol", items: run.lines.map((l) => l.replace(NUMBER, "")), start });
      } else if (run.kind === "math") {
        blocks.push({ kind: "math", lines: run.lines.map((l) => l.trim()) });
      } else {
        blocks.push({ kind: "p", text: run.lines.join("\n").trim() });
      }
    }
  }
  return blocks;
}

type Run = { kind: "p" | "ul" | "ol" | "math"; lines: string[] };

function kindOf(line: string): Run["kind"] {
  if (BULLET.test(line)) return "ul";
  if (NUMBER.test(line)) return "ol";
  if (isWorking(line)) return "math";
  return "p";
}

/** Consecutive lines of one kind, in order. */
function runs(lines: string[]): Run[] {
  const out: Run[] = [];
  for (const line of lines) {
    const kind = kindOf(line);
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.lines.push(line);
    else out.push({ kind, lines: [line] });
  }
  return out;
}
