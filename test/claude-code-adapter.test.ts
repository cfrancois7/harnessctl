import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { getAdapter } from "../src/adapters/adapter.js";
import { loadCatalog, resolveModule } from "../src/catalog/load.js";
import { CAPABILITIES, type Operation } from "../src/types.js";

const catalogs = [
  loadCatalog(join(import.meta.dirname, "fixtures/catalog")),
  loadCatalog(join(import.meta.dirname, "fixtures/company-catalog")),
];
const adapter = getAdapter("claude-code");
const env = { home: "/home/u" };
const byKind = <K extends Operation["kind"]>(ops: Operation[], kind: K) =>
  ops.filter((o): o is Extract<Operation, { kind: K }> => o.kind === kind);

describe("claude-code adapter", () => {
  it("reports every capability and rejects unknown adapters", () => {
    expect(adapter.capabilities()).toEqual([...CAPABILITIES]);
    expect(() => getAdapter("emacs")).toThrowError(/unknown harness "emacs".*claude-code/);
  });

  it("confines user scope to Claude Code's own files", () => {
    expect(adapter.allowedPrefixes("project")).toEqual([""]);
    expect(adapter.allowedPrefixes("user")).toEqual([".claude/", ".claude.json"]);
  });

  const alpha = resolveModule(catalogs, "alpha");
  const ops = adapter.translate(alpha, { greeting: "hi", areas: ["api", "fw"] }, "project", env);

  it("copies skills, hook scripts, the runtime, and a config file", () => {
    const owned = byKind(ops, "writeOwned");
    expect(owned.map((o) => o.target)).toEqual([
      ".claude/skills/alpha-skill/SKILL.md",
      ".claude/kit/runtime.mjs",
      ".claude/kit/hooks/alpha/check.mjs",
      ".claude/kit/hooks/alpha/start.mjs",
      ".claude/kit/config/alpha.json",
    ]);
    expect(owned[0]!.content).toBe(alpha.files["skills/alpha-skill/SKILL.md"]);
    expect(owned[1]!.content).toContain("export async function run");
    expect(JSON.parse(owned[4]!.content)).toEqual({
      module: "alpha", version: "1.0.0", scope: "project",
      onError: { "check.mjs": "allow", "start.mjs": "deny" },
      values: { greeting: "hi", areas: ["api", "fw"] },
    });
    expect(owned.every((o) => o.module === "alpha")).toBe(true);
  });

  it("registers hooks with Claude Code event and tool names", () => {
    const settings = byKind(ops, "mergeJson").filter((o) => o.target === ".claude/settings.json");
    expect(settings).toEqual([
      { kind: "mergeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "PreToolUse"],
        value: { matcher: "Bash", hooks: [{ type: "command",
          command: 'node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/check.mjs' }] },
        match: { commandContains: "kit/hooks/alpha/check.mjs" } },
      // start.mjs is declared onError "deny": the fail-closed policy travels in the command itself.
      { kind: "mergeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "SessionStart"],
        value: { hooks: [{ type: "command",
          command: 'node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/start.mjs --kit-on-error=deny' }] },
        match: { commandContains: "kit/hooks/alpha/start.mjs" } },
    ]);
  });

  it("F2: marks fail-closed hooks in the command without breaking the match", () => {
    const settings = byKind(ops, "mergeJson").filter((o) => o.target === ".claude/settings.json");
    const command = (o: (typeof settings)[number]) =>
      (o.value as { hooks: { command: string }[] }).hooks[0]!.command;
    const deny = settings.find((o) => o.match!.commandContains.endsWith("start.mjs"))!;
    const allow = settings.find((o) => o.match!.commandContains.endsWith("check.mjs"))!;

    expect(command(deny).endsWith(" --kit-on-error=deny")).toBe(true);
    expect(command(allow)).not.toContain("--kit-on-error");
    for (const o of [deny, allow]) expect(command(o)).toContain(o.match!.commandContains);
  });

  it("merges MCP servers, renders instructions into a block, and scaffolds", () => {
    expect(byKind(ops, "mergeJson").find((o) => o.target === ".mcp.json")).toEqual({
      kind: "mergeJson", module: "alpha", target: ".mcp.json", path: ["mcpServers", "alpha-mcp"],
      value: { command: "alpha-mcp", env: { TOKEN: "${ALPHA_TOKEN}" } } });
    expect(byKind(ops, "markedBlock")).toEqual([{
      kind: "markedBlock", module: "alpha", target: "CLAUDE.md", id: "alpha",
      content: '## Alpha\n\nGreeting is "hi". Areas: api, fw.' }]);
    expect(byKind(ops, "scaffoldOnce")).toEqual([{
      kind: "scaffoldOnce", module: "alpha", target: "docs/context/INDEX.md",
      content: "# Context index (alpha 1.0.0)\n\nAreas: api, fw\n" }]);
  });

  it("uses absolute commands and user-level files at user scope", () => {
    const beta = resolveModule(catalogs, "beta");
    const userOps = adapter.translate(beta, { mode: "warn" }, "user", env);
    const hook = byKind(userOps, "mergeJson")[0]!;
    expect(hook.value).toEqual({ matcher: "Agent", hooks: [{ type: "command",
      command: 'node "/home/u/.claude/kit/hooks/beta/guard.mjs"' }] });
    expect(JSON.parse(byKind(userOps, "writeOwned").at(-1)!.content).scope).toBe("user");
  });

  it("emits no runtime or config for a module without hooks", () => {
    const gamma = resolveModule(catalogs, "gamma");
    const gammaOps = adapter.translate(gamma, {}, "project", env);
    expect(gammaOps.map((o) => o.kind)).toEqual(["markedBlock"]);
  });

  it("merges MCP servers into .claude.json at user scope, never .mcp.json", () => {
    const beta = resolveModule(catalogs, "beta");
    const synthetic = { ...beta, contributes: { ...beta.contributes, mcpServers: { x: { command: "x" } } } };
    const userOps = adapter.translate(synthetic, { mode: "warn" }, "user", env);
    expect(byKind(userOps, "mergeJson")).toContainEqual({
      kind: "mergeJson", module: "beta", target: ".claude.json", path: ["mcpServers", "x"],
      value: { command: "x" },
    });
    expect(userOps.some((o) => "target" in o && o.target === ".mcp.json")).toBe(false);
  });
});
