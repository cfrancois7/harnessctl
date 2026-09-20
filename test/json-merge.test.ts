import { describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import {
  fromPointer, hasJsonEntry, isEmptyJson, removeJsonEntry, toPointer, upsertJsonEntry,
} from "../src/ops/json-merge.js";

const hookEntry = (module: string, script: string, matcher?: string) => ({
  ...(matcher ? { matcher } : {}),
  hooks: [{ type: "command", command: `node x/kit/hooks/${module}/${script}` }],
});
const M1 = { commandContains: "kit/hooks/m/check.mjs" };
const M2 = { commandContains: "kit/hooks/m/start.mjs" };
const M3 = { commandContains: "kit/hooks/n/check.mjs" };

const CASES: Record<string, string> = {
  canonical2: `{\n  "permissions": {\n    "allow": ["Bash(npm test)"]\n  },\n  "model": "sonnet"\n}\n`,
  compactSiblingsAndComment: `{\n    "permissions": { "allow": [] },\n    // a comment\n    "hooks": {\n        "PreToolUse": [\n            { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo hi" }] }\n        ]\n    }\n}\n`,
  compactLastProperty: `{\n  "model": "sonnet",\n  "permissions": { "allow": [] }\n}\n`,
  oneLine: `{"model":"sonnet"}`,
  tabs: `{\n\t"a": 1\n}\n`,
  crlf: `{\r\n  "a": 1\r\n}\r\n`,
  emptyObject: `{}\n`,
};

function installAll(text: string): string {
  let t = upsertJsonEntry(text, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Agent"), M1);
  t = upsertJsonEntry(t, "f", ["hooks", "PreToolUse"], hookEntry("n", "check.mjs", "Bash"), M3);
  t = upsertJsonEntry(t, "f", ["hooks", "SessionStart"], hookEntry("m", "start.mjs"), M2);
  return upsertJsonEntry(t, "f", ["mcpServers", "plm"], { command: "plm-mcp" });
}

describe.each(Object.entries(CASES))("json merge on %s", (_name, original) => {
  it("adds entries and keeps the result valid", () => {
    const parsed = JSON.parse(installAll(original).replace(/^\s*\/\/.*$/gm, ""));
    expect(parsed.hooks.PreToolUse.at(-2).matcher).toBe("Agent");
    expect(parsed.hooks.PreToolUse.at(-1).matcher).toBe("Bash");
    expect(parsed.hooks.SessionStart).toHaveLength(1);
    expect(parsed.mcpServers.plm).toEqual({ command: "plm-mcp" });
  });

  it("does not touch text it does not own", () => {
    const installed = installAll(original);
    // Compare each original line minus its outermost bracket/comma, which an insertion may legitimately follow.
    const core = (line: string) => line.trim().replace(/^[{[]\s*/, "").replace(/\s*[}\]]?,?$/, "");
    for (const line of original.split(/\r?\n/).map(core).filter((l) => l !== "")) {
      expect(installed).toContain(line);
    }
    expect(installAll(original)).not.toBe(original);
  });

  it("is idempotent", () => {
    const once = installAll(original);
    expect(installAll(once)).toBe(once);
  });

  it("round-trips byte-for-byte when entries are removed in a different order", () => {
    let t = installAll(original);
    t = removeJsonEntry(t, "f", ["hooks", "PreToolUse"], M1);
    t = removeJsonEntry(t, "f", ["mcpServers", "plm"]);
    t = removeJsonEntry(t, "f", ["hooks", "SessionStart"], M2);
    t = removeJsonEntry(t, "f", ["hooks", "PreToolUse"], M3);
    expect(t).toBe(original);
  });
});

describe("json merge details", () => {
  it("treats empty text as an empty object", () => {
    const t = upsertJsonEntry("", "f", ["mcpServers", "a"], { command: "a" });
    expect(JSON.parse(t)).toEqual({ mcpServers: { a: { command: "a" } } });
    expect(isEmptyJson(removeJsonEntry(t, "f", ["mcpServers", "a"]))).toBe(true);
  });

  it("replaces a matched array entry instead of appending", () => {
    let t = upsertJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Agent"), M1);
    t = upsertJsonEntry(t, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Bash"), M1);
    const arr = JSON.parse(t).hooks.PreToolUse;
    expect(arr).toHaveLength(1);
    expect(arr[0].matcher).toBe("Bash");
  });

  it("reports presence", () => {
    const t = installAll(CASES.canonical2!);
    expect(hasJsonEntry(t, "f", ["hooks", "PreToolUse"], M1)).toBe(true);
    expect(hasJsonEntry(t, "f", ["mcpServers", "plm"])).toBe(true);
    expect(hasJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], M1)).toBe(false);
    expect(hasJsonEntry(CASES.canonical2!, "f", ["mcpServers", "plm"])).toBe(false);
  });

  it("removal of something absent is a no-op", () => {
    expect(removeJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], M1)).toBe(CASES.canonical2);
    expect(removeJsonEntry(CASES.canonical2!, "f", ["mcpServers", "zzz"])).toBe(CASES.canonical2);
  });

  it("refuses files it cannot parse, and non-object roots", () => {
    expect(() => upsertJsonEntry("{ nope", "settings.json", ["a"], 1))
      .toThrowError(new KitError("cannot parse settings.json: not a valid JSON object"));
    expect(() => upsertJsonEntry("[1]", "settings.json", ["a"], 1)).toThrowError(KitError);
    expect(() => upsertJsonEntry('{"hooks":{"PreToolUse":{}}}', "s.json", ["hooks", "PreToolUse"], {}, M1))
      .toThrowError(/s\.json: \/hooks\/PreToolUse is not an array/);
  });

  it("isEmptyJson is false when comments remain", () => {
    expect(isEmptyJson("{}\n")).toBe(true);
    expect(isEmptyJson("{\n  // keep me\n}\n")).toBe(false);
    expect(isEmptyJson('{"a":1}')).toBe(false);
    expect(isEmptyJson("not json")).toBe(false);
  });

  it("converts JSON pointers", () => {
    expect(toPointer(["mcpServers", "a/b~c"])).toBe("/mcpServers/a~1b~0c");
    expect(fromPointer("/mcpServers/a~1b~0c")).toEqual(["mcpServers", "a/b~c"]);
  });
});
