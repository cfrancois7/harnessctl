import { appendFileSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { inProject, makeWorkspace, runKit, type Workspace } from "./cli-helpers.js";
import { commitAll } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[]) => runKit(args, { cwd: ws.project, home: ws.home });

beforeEach(async () => {
  ws = makeWorkspace();
  process.env.ALPHA_TOKEN = "set";
  await kit(["init", "--profile", "dev", "--yes"]);
});
afterEach(() => {
  delete process.env.ALPHA_TOKEN;
});

describe("kit status", () => {
  it("is clean right after install", async () => {
    expect(await kit(["status"])).toMatchObject({ code: 0, output: expect.stringContaining("ok: 2 modules, no problems") });
  });

  it("reports drift, missing env vars, outdated modules and duplicates, and exits 1", async () => {
    rmSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"));
    appendFileSync(inProject(ws, ".claude/skills/alpha-skill/SKILL.md"), "edit\n");
    writeFileSync(inProject(ws, ".mcp.json"), "{}\n");
    writeFileSync(inProject(ws, "CLAUDE.md"), "# mine\n");
    delete process.env.ALPHA_TOKEN;
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    const manifest = join(ws.publicRepo, "modules/alpha/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace('"1.0.0"', '"1.1.0"'));
    commitAll(ws.publicRepo, "release");

    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    for (const expected of [
      "project alpha: missing .claude/kit/hooks/alpha/start.mjs",
      "project alpha: modified .claude/skills/alpha-skill/SKILL.md",
      "project alpha: missing entry /mcpServers/alpha-mcp in .mcp.json",
      "project alpha: missing block in CLAUDE.md",
      "project alpha: env var ALPHA_TOKEN is not set",
      "project alpha: outdated (1.0.0 installed, 1.1.0 available)",
      "user beta: duplicate (also installed at project scope; the project install wins)",
    ]) expect(r.output).toContain(expected);
  });

  it("still checks files when catalogs are unreachable", async () => {
    rmSync(ws.publicRepo, { recursive: true, force: true });
    rmSync(join(ws.home, ".cache"), { recursive: true, force: true });
    rmSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"));
    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    expect(r.output).toContain("warning:");
    expect(r.output).toContain("missing .claude/kit/hooks/alpha/start.mjs");
  });

  it("reports a damaged block and still reports a missing owned file, instead of aborting", async () => {
    const claudeMd = inProject(ws, "CLAUDE.md");
    writeFileSync(claudeMd, readFileSync(claudeMd, "utf8").split("\n").filter((l) => !l.includes("kit:alpha:end")).join("\n"));
    rmSync(inProject(ws, ".claude/kit/hooks/alpha/check.mjs"));

    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    expect(r.output).not.toMatch(/^error:/);
    expect(r.output).toContain("no end marker");
    expect(r.output).toContain("missing .claude/kit/hooks/alpha/check.mjs");
  });

  it("reports an unsafe owned path from the lockfile as an issue and still checks the rest", async () => {
    const lockFile = inProject(ws, ".harness-kit/lock.json");
    const lock = JSON.parse(readFileSync(lockFile, "utf8"));
    lock.modules.alpha.owned.files[0].path = "../evil";
    writeFileSync(lockFile, JSON.stringify(lock, null, 2));
    delete process.env.ALPHA_TOKEN;

    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    expect(r.output).not.toMatch(/^error:/);
    expect(r.output).toContain("unsafe target path");
    expect(r.output).toContain("../evil");
    expect(r.output).toContain("project alpha: env var ALPHA_TOKEN is not set");
  });
});

describe("kit list", () => {
  it("shows catalog modules with support and install marks", async () => {
    const r = await kit(["list"]);
    expect(r.code).toBe(0);
    expect(r.output).toMatch(/public:alpha\s+1\.0\.0\s+project\s+supported\s+installed \(project 1\.0\.0\)/);
    expect(r.output).toMatch(/public:beta\s+0\.2\.0\s+user,project\s+supported\s+installed \(user 0\.2\.0\)/);
  });

  it("marks outdated installs", async () => {
    const manifest = join(ws.publicRepo, "modules/alpha/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace('"1.0.0"', '"1.1.0"'));
    commitAll(ws.publicRepo, "release");
    expect((await kit(["list"])).output).toMatch(/public:alpha\s+1\.1\.0.*installed \(project 1\.0\.0, outdated\)/);
  });
});
