/** The little structure the agent may use beyond paragraphs, read out of plain text: a list, one
 * item per line starting with "- " or "1.", and a simple table, one row per line with | between
 * cells. Anything else is a paragraph, line breaks kept. No markup is interpreted. */

export type Block =
  | { kind: "p"; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[]; start: number }
  | { kind: "table"; head: string[]; rows: string[][] };

const BULLET = /^\s*[-*•]\s+/;
const NUMBER = /^\s*(\d+)[.)]\s+/;
const RULE = /^:?-{2,}:?$/;
const FRAMED = /^\s*\|.*\|\s*$/;

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
    if (lines.every((l) => BULLET.test(l))) {
      blocks.push({ kind: "ul", items: lines.map((l) => l.replace(BULLET, "")) });
      continue;
    }
    if (lines.every((l) => NUMBER.test(l))) {
      // A list that carries on after a paragraph keeps its numbers: 3, 4 stays 3, 4.
      const start = Number(lines[0].match(NUMBER)?.[1] ?? 1);
      blocks.push({ kind: "ol", items: lines.map((l) => l.replace(NUMBER, "")), start });
      continue;
    }
    blocks.push({ kind: "p", text: chunk.trim() });
  }
  return blocks;
}
