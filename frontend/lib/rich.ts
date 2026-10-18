/** The little structure the agent may use beyond paragraphs, read out of plain text: a list, one
 * item per line starting with "- " or "1.", and a simple table, one row per line with | between
 * cells. Anything else is a paragraph, line breaks kept. No markup is interpreted. */

export type Block =
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] };

const BULLET = /^\s*[-*•]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;
const RULE = /^:?-{2,}:?$/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of text.replace(/\r/g, "").split(/\n\s*\n/)) {
    const lines = chunk.split("\n").filter((l) => l.trim() !== "");
    if (lines.length === 0) continue;
    if (lines.length >= 2 && lines.every((l) => l.includes("|"))) {
      const rows = lines
        .map((l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()))
        .filter((cells) => !cells.every((c) => RULE.test(c)));
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
      blocks.push({ kind: "ol", items: lines.map((l) => l.replace(NUMBER, "")) });
      continue;
    }
    blocks.push({ kind: "p", text: chunk.trim() });
  }
  return blocks;
}
