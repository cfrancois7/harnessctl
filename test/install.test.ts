import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { inHome, inProject, makeWorkspace, runKit, type Answers, type Workspace } from "./cli-helpers.js";
import { git, snapshotTree } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[], answers?: Answers) => runKit(args, { cwd: ws.project, home: ws.home, answers });
const readJson = (path: string) => JSON.parse(readFileSync(path, "utf8"));

beforeEach(() => {
  ws = makeWorkspace();
});

describe("kit init", () => {
  it("installs a profile non-interactively at both scopes", async () => {
    const r = await kit(["init", "--profile", "dev", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.asked).toEqual([]);

    expect(existsSync(inProject(ws, ".claude/skills/alpha-skill/SKILL.md"))).toBe(true);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8")).toContain('Greeting is "hi dev"');
    expect(readFileSync(inProject(ws, "docs/context/INDEX.md"), "utf8")).toContain("Areas: api");
    expect(readJson(inProject(ws, ".mcp.json")).mcpServers["alpha-mcp"].command).toBe("alpha-mcp");
    const settings = readJson(inProject(ws, ".claude/settings.json"));
    expect(settings.hooks.PreToolUse[0].hooks[0].command)
      .toBe('node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/check.mjs');

    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.profile).toBe("dev");
    expect(lock.modules.alpha).toMatchObject({ catalog: "public", version: "1.0.0", config: { greeting: "hi dev", areas: ["api"] } });
    expect(lock.modules.alpha.scaffolded).toEqual(["docs/context/INDEX.md"]);
    expect(lock.catalogs.public).toEqual({ url: ws.publicRepo, sha: git(ws.publicRepo, "rev-parse", "HEAD") });
    expect(lock.createdFiles).toEqual([".claude/settings.json", ".mcp.json", "CLAUDE.md"]);

    expect(existsSync(inHome(ws, ".claude/kit/hooks/beta/guard.mjs"))).toBe(true);
    expect(readJson(inHome(ws, ".claude/settings.json")).hooks.PreToolUse[0].hooks[0].command)
      .toBe(`node "${ws.home}/.claude/kit/hooks/beta/guard.mjs"`);
    expect(readJson(inHome(ws, ".config/harness-kit/lock.json")).modules.beta.version).toBe("0.2.0");
  });

  it("installed hooks actually run from their installed location", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const result = spawnSync(process.execPath, [inProject(ws, ".claude/kit/hooks/alpha/check.mjs")], {
      encoding: "utf8",
      input: JSON.stringify({ hook_event_name: "PreToolUse", tool_name: "Bash", session_id: "s", cwd: ws.project,
                              tool_input: { command: "echo alpha-deny-me" } }),
    });
    expect(JSON.parse(result.stdout).hookSpecificOutput).toMatchObject({
      permissionDecision: "deny", permissionDecisionReason: "alpha (hi dev) blocked this command" });
  });

  it("requires a profile when non-interactive", async () => {
    expect(await kit(["init", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("--yes needs --profile") });
  });

  it("walks through profile, module checklist, config and confirmation", async () => {
    const r = await kit(["init"], {
      select: ["dev"], multiselect: [["public:alpha"]], text: ["howdy", "api, firmware"], confirm: [true] });
    expect(r.code).toBe(0);
    expect(r.asked).toEqual([
      "Profile", "Modules to install", "alpha › Greeting", "alpha › Areas (comma-separated)",
      "Apply these changes to project scope?"]);
    expect(readJson(inProject(ws, ".claude/kit/config/alpha.json")).values).toEqual({ greeting: "howdy", areas: ["api", "firmware"] });
    expect(existsSync(inHome(ws, ".claude"))).toBe(false); // beta was unticked
  });

  it("writes nothing on --dry-run or when the user declines", async () => {
    const before = snapshotTree(ws.project);
    const dry = await kit(["init", "--profile", "dev", "--yes", "--dry-run"]);
    expect(dry.output).toContain("+ .claude/skills/alpha-skill/SKILL.md");
    expect(dry.output).toContain("dry run: nothing written");
    await kit(["init", "--profile", "dev"], { multiselect: [["public:alpha"]], confirm: [false] });
    expect(snapshotTree(ws.project)).toEqual(before);
  });

  it("preserves hand-written settings", async () => {
    mkdirSync(inProject(ws, ".claude"));
    writeFileSync(inProject(ws, ".claude/settings.json"),
      `{\n  "permissions": { "allow": ["Bash(npm test)"] },\n  "hooks": {\n    "PreToolUse": [\n      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }\n    ]\n  }\n}\n`);
    await kit(["init", "--profile", "dev", "--yes"]);
    const text = readFileSync(inProject(ws, ".claude/settings.json"), "utf8");
    expect(text).toContain(`"permissions": { "allow": ["Bash(npm test)"] },`);
    expect(text).toContain(`{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }`);
    expect(JSON.parse(text).hooks.PreToolUse).toHaveLength(2);
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).createdFiles).not.toContain(".claude/settings.json");
  });

  it("explains how to add a catalog when none is configured", async () => {
    const r = await runKit(["init", "--profile", "dev", "--yes"], { cwd: ws.project, home: inHome(ws, "empty") });
    expect(r).toMatchObject({ code: 1, output: expect.stringContaining("kit catalog add") });
  });

  it("does not touch any scope when another scope's plan fails", async () => {
    mkdirSync(inHome(ws, ".claude"), { recursive: true });
    writeFileSync(inHome(ws, ".claude/settings.json"), "{ nope");
    const before = snapshotTree(ws.project);

    const r = await kit(["init", "--profile", "dev", "--yes"]);

    expect(r.code).toBe(1);
    expect(r.output).toContain("cannot parse");
    expect(r.output).toContain("settings.json");
    expect(snapshotTree(ws.project)).toEqual(before);
    expect(readFileSync(inHome(ws, ".claude/settings.json"), "utf8")).toBe("{ nope");
  });
});

describe("kit add", () => {
  it("installs a module at a chosen scope and shares the runtime shim", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const r = await kit(["add", "beta", "--scope", "project", "--yes"]);
    expect(r.code).toBe(0);
    const settings = readJson(inProject(ws, ".claude/settings.json"));
    expect(settings.hooks.PreToolUse.map((e: { matcher: string }) => e.matcher)).toEqual(["Bash", "Agent"]);
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    const owners = Object.entries(lock.modules)
      .filter(([, m]) => (m as { owned: { files: { path: string }[] } }).owned.files.some((f) => f.path === ".claude/kit/runtime.mjs"))
      .map(([name]) => name);
    expect(owners.sort()).toEqual(["alpha", "beta"]);
  });

  it("F1: keeps an MCP server the user already had under the same name, and never removes it", async () => {
    const mine = `{\n  "mcpServers": {\n    "alpha-mcp": { "command": "my-own-alpha" }\n  }\n}\n`;
    writeFileSync(inProject(ws, ".mcp.json"), mine);

    const r = await kit(["add", "alpha", "--scope", "project", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("kept your version of .mcp.json#/mcpServers/alpha-mcp");
    expect(readFileSync(inProject(ws, ".mcp.json"), "utf8")).toBe(mine);

    expect((await kit(["remove", "alpha", "--yes"])).code).toBe(0);
    expect(readFileSync(inProject(ws, ".mcp.json"), "utf8")).toBe(mine);
  });

  it("prompts for config and rejects unknown modules and unsupported scopes", async () => {
    const r = await kit(["add", "beta"], { select: ["block"], confirm: [true] });
    expect(r.asked).toEqual(["beta › Mode", "Apply these changes to user scope?"]);
    expect(readJson(inHome(ws, ".claude/kit/config/beta.json")).values).toEqual({ mode: "block" });
    expect(await kit(["add", "nope", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining('module "nope" not found') });
    expect(await kit(["add", "alpha", "--scope", "user", "--yes"]))
      .toMatchObject({ code: 1, output: expect.stringContaining("does not support user scope") });
    expect(await kit(["add"])).toMatchObject({ code: 1, output: expect.stringContaining("usage: kit add") });
  });
});
