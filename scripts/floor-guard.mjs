#!/usr/bin/env node
// floor-guard.mjs: the CONSTRAINTS.md floor, checked on a diff.
//
// Adapted from the constraint-driven-development reference guard. It looks only at what
// changed (added and removed lines, staged or not, plus new untracked files) and flags the
// moves that lower the bar: a silenced checker, unfinished work, a test made easier, an
// assertion taken out, a new exception, a weakened threshold.
//
// Usage: node scripts/floor-guard.mjs [--base <ref>]   (default base: HEAD, i.e. uncommitted work)
// Exit:  0 clean, 1 at least one floor violation, 2 the guard could not run.
// It reports the rule and the place, never a matched value.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const argBase = (() => {
  const i = process.argv.indexOf("--base");
  return i > -1 ? process.argv[i + 1] : "HEAD";
})();

const git = (args) => {
  try {
    return execFileSync("git", args, {
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (e) {
    // `git diff --no-index` exits 1 when the files differ, which is the normal case.
    return e.stdout ?? null;
  }
};

if (git(["rev-parse", "--is-inside-work-tree"])?.trim() !== "true") {
  console.error("floor-guard: not inside a git work tree");
  process.exit(2);
}
const base = argBase === "HEAD" ? "HEAD" : git(["merge-base", argBase, "HEAD"])?.trim();
if (!base || git(["rev-parse", "--verify", "--quiet", base]) === null) {
  console.error(`floor-guard: no base to compare against (${argBase})`);
  process.exit(2);
}

// The unified diff of tracked files, plus every untracked file as a new file.
const tracked = git(["diff", "--unified=0", base, "--"]) ?? "";
const untracked = (git(["ls-files", "--others", "--exclude-standard"]) ?? "")
  .split("\n")
  .filter(Boolean)
  .map((f) => git(["diff", "--no-index", "--unified=0", "/dev/null", f]) ?? "")
  .join("\n");
const diff = `${tracked}\n${untracked}`;

const added = [];
const removed = [];
const deletedFiles = new Set();
let file = "";
let oldFile = "";
for (const line of diff.split("\n")) {
  if (line.startsWith("--- ")) oldFile = line.slice(4).replace(/^a\//, "");
  else if (line.startsWith("+++ ")) {
    file = line.slice(4).replace(/^b\//, "");
    if (file === "/dev/null") {
      file = oldFile;
      deletedFiles.add(oldFile);
    }
  } else if (line.startsWith("+")) added.push({ file, text: line.slice(1) });
  else if (line.startsWith("-")) removed.push({ file, text: line.slice(1) });
}

const findings = [];
const flag = (rule, where, text) =>
  findings.push({ rule, file: where, text: text.trim().slice(0, 120) });

// Only source files are read for patterns: docs and CONSTRAINTS.md name these words on purpose.
const CODE = /\.(py|ts|tsx|js|mjs|cjs|jsx|sql|sh)$/;
const SELF = "scripts/floor-guard.mjs";
const TEST_FILE = /(^|\/)(tests?\/|test_[^/]*\.py$|[^/]*_test\.py$|[^/]*\.(test|spec)\.[jt]sx?$)/;

// 1. A silenced checker: lint, type, coverage and security suppressions, Python and TypeScript.
const SUPPRESSIONS =
  /@ts-ignore|@ts-nocheck|@ts-expect-error|eslint-disable|biome-ignore|\bnoqa\b|type: *ignore|pyright: *ignore|pragma: *no cover|istanbul ignore|c8 ignore|nosemgrep|\bnosec\b|gitleaks:allow|Stryker disable/;
// 4. Unfinished work.
const STUBS =
  /throw new (Error|NotImplemented)\(.*[Nn]ot implemented|raise NotImplementedError|catch\s*(\(\w*\))?\s*\{\s*\}|except[^:]*:\s*pass\s*$|\bTODO\b|\bFIXME\b/;
// 2. A test made easier: a skip or an expected failure added.
const SKIPS =
  /\.(skip|todo)\(|\bxit\(|\bxdescribe\(|@pytest\.mark\.(skip|skipif|xfail)\b|pytest\.skip\(|pytest\.xfail\(/;

for (const { file: f, text } of added) {
  if (f === SELF || !CODE.test(f)) continue;
  if (SUPPRESSIONS.test(text)) flag("silenced-checker", f, text);
  if (STUBS.test(text)) flag("unfinished-work", f, text);
  if (SKIPS.test(text)) flag("test-made-easier", f, text);
}

// 2b. Assertions taken out of tests: fewer asserts in a test file than before, or a test file
// deleted. Rewriting an assertion (one out, one in) is not a loss.
const ASSERT = /\b(assert|expect)\b/;
const net = new Map();
for (const { file: f, text } of removed)
  if (TEST_FILE.test(f) && ASSERT.test(text)) net.set(f, (net.get(f) ?? 0) - 1);
for (const { file: f, text } of added)
  if (TEST_FILE.test(f) && ASSERT.test(text)) net.set(f, (net.get(f) ?? 0) + 1);
for (const [f, n] of net) {
  if (n < 0)
    flag(
      deletedFiles.has(f) ? "test-file-deleted" : "assertion-removed",
      f,
      `${-n} fewer assertion line(s)`,
    );
}

// 5. A new exception: a row in the Exceptions table, a secret-scan allowance, a new entry in
// the baseline's allow list.
for (const { file: f, text } of added) {
  if (f === "CONSTRAINTS.md" && /^\| *[EW]\d+ *\|/.test(text)) flag("new-exception", f, text);
  if (f === ".gitleaksignore" && text.trim() && !text.trim().startsWith("#"))
    flag("new-exception", f, "a new secret-scan allowance");
}

// 1b. A weakened threshold in CONSTRAINTS.md, or a floor rule deleted. Table rows are compared
// cell by cell, in the row's own direction: most numbers are floors (lower is looser), but a
// "must not grow" count is a ceiling and an exception's expiry is a deadline (higher is looser).
const nums = (s) => (s.match(/\d+(\.\d+)?/g) || []).map(Number);
const head = (s) => s.split(/[|:]/).filter((x) => x.trim())[0]?.trim();
const cells = (s) => s.trim().replace(/^\||\|$/g, "").split("|");
const ceiling = (s) =>
  /must not grow|at most|no more than|or fewer/i.test(s) || /^[EW]\d+$/.test(head(s) ?? "");
const looserRow = (before, after) => {
  const higherIsLooser = ceiling(before);
  const [b, a] = [cells(before), cells(after)];
  return b.some((cell, i) => {
    const [bn, an] = [nums(cell), nums(a[i] ?? "")];
    return bn.some((n, j) => an[j] !== undefined && (higherIsLooser ? an[j] > n : an[j] < n));
  });
};
// Only sections that hold a bar count: "How to run" lists durations, not thresholds.
const sectionOf = (source, line) => {
  let section = "";
  for (const l of (source ?? "").split("\n")) {
    if (l.startsWith("## ")) section = l.slice(3).trim();
    if (l === line) return section;
  }
  return section;
};
const oldConstraints = git(["show", `${base}:CONSTRAINTS.md`]) ?? "";
const NOT_A_BAR = new Set(["How to run"]);
const cRemoved = removed.filter(
  (l) => l.file === "CONSTRAINTS.md" && !NOT_A_BAR.has(sectionOf(oldConstraints, l.text)),
);
const cAdded = added.filter((l) => l.file === "CONSTRAINTS.md");
for (const r of cRemoved) {
  const a = cAdded.find((x) => head(x.text) && head(x.text) === head(r.text));
  if (a) {
    const isRow = r.text.trim().startsWith("|") && a.text.trim().startsWith("|");
    const before = nums(r.text);
    const looser = isRow
      ? looserRow(r.text, a.text)
      : nums(a.text).some((n, i) => before[i] !== undefined && n < before[i]);
    if (looser)
      flag("threshold-lowered", "CONSTRAINTS.md", `${r.text.trim()}  ->  ${a.text.trim()}`);
  } else if (/^- /.test(r.text.trim()) && cRemoved.length > cAdded.length) {
    flag("floor-rule-removed", "CONSTRAINTS.md", r.text);
  }
}

// 1c. The baseline the check script holds the line with, loosened.
const BASELINE = "constraints.baseline.json";
if (added.some((l) => l.file === BASELINE) || removed.some((l) => l.file === BASELINE)) {
  const read = (s) => {
    try {
      return JSON.parse(s);
    } catch {
      return null;
    }
  };
  const before = read(git(["show", `${base}:${BASELINE}`]) ?? "");
  const after = read(readFileSync(BASELINE, "utf8"));
  if (!after) flag("baseline-unreadable", BASELINE, "the baseline is not valid JSON");
  else if (before) {
    const looser = (key, dir) => {
      const a = after.hold?.[key];
      const b = before.hold?.[key];
      if (a === undefined && b !== undefined) return true;
      return dir === "min" ? a < b : a > b;
    };
    for (const [key, spec] of Object.entries(before.hold ?? {}))
      if (typeof spec === "number" && looser(key, before.directions?.[key]))
        flag("threshold-lowered", BASELINE, `${key}: ${before.hold[key]} -> ${after.hold?.[key]}`);
    const allowed = (x) => new Set((x.semgrep_allowed ?? []).map((p) => p.join(" ")));
    const was = allowed(before);
    for (const p of allowed(after)) if (!was.has(p)) flag("new-exception", BASELINE, p);
    if ((after.warn_until ?? "") > (before.warn_until ?? ""))
      flag("threshold-lowered", BASELINE, `warn_until moved later: ${after.warn_until}`);
  }
}

if (findings.length === 0) {
  console.log("floor-guard: clean");
  process.exit(0);
}
console.error(`floor-guard: ${findings.length} floor violation(s):`);
for (const f of findings) console.error(`  [${f.rule}] ${f.file}: ${f.text}`);
console.error(
  "\nEach is a move that lowers the bar. Fix the code, or route it through a tracked exception in CONSTRAINTS.md.",
);
process.exit(1);
