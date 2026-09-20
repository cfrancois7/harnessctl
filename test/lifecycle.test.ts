import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { inHome, inProject, makeWorkspace, runKit, type Answers, type Workspace } from "./cli-helpers.js";
import { commitAll, snapshotTree } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[], answers?: Answers) => runKit(args, { cwd: ws.project, home: ws.home, answers });
const readJson = (path: string) => JSON.parse(readFileSync(path, "utf8"));
const SKILL = ".claude/skills/alpha-skill/SKILL.md";

function releaseAlpha(edit: (manifest: any) => void, files: Record<string, string | null> = {}): string {
  const dir = join(ws.publicRepo, "modules/alpha");
  const manifest = readJson(join(dir, "module.json"));
  edit(manifest);
  writeFileSync(join(dir, "module.json"), JSON.stringify(manifest, null, 2));
  for (const [rel, content] of Object.entries(files)) {
    if (content === null) rmSync(join(dir, rel));
    else writeFileSync(join(dir, rel), content);
  }
  return commitAll(ws.publicRepo, "release alpha");
}

beforeEach(async () => {
  ws = makeWorkspace();
  await kit(["init", "--profile", "dev", "--yes"]);
});

describe("kit remove", () => {
  it("removes everything the module owns and leaves scaffolded files", async () => {
    const r = await kit(["remove", "alpha", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("left in place (yours now): docs/context/INDEX.md");
    for (const gone of [".claude", ".mcp.json", "CLAUDE.md"]) expect(existsSync(inProject(ws, gone))).toBe(false);
    expect(existsSync(inProject(ws, "docs/context/INDEX.md"))).toBe(true);
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.modules).toEqual({});
    expect(lock.catalogs).toEqual({});
    expect(lock.createdFiles).toEqual([]);
  });

  it("deletes the shared runtime when all its owners are removed together", async () => {
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    await kit(["remove", "alpha", "--yes"]);
    expect(existsSync(inProject(ws, ".claude/kit/runtime.mjs"))).toBe(true); // beta still needs it
    await kit(["add", "alpha", "--yes"]);
    await kit(["remove", "alpha", "beta", "--scope", "project", "--yes"]);
    expect(existsSync(inProject(ws, ".claude"))).toBe(false);
  });

  it("needs --scope when a module is installed at both scopes", async () => {
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    expect(await kit(["remove", "beta", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("pass --scope") });
    expect((await kit(["remove", "beta", "--scope", "user", "--yes"])).code).toBe(0);
    expect(existsSync(inHome(ws, ".claude"))).toBe(false);
    expect(existsSync(inProject(ws, ".claude/kit/hooks/beta/guard.mjs"))).toBe(true);
  });

  it("asks before deleting module state, and keeps it under --yes", async () => {
    const state = inHome(ws, ".config/harness-kit/state/beta");
    mkdirSync(state, { recursive: true });
    await kit(["remove", "beta", "--yes"]);
    expect(existsSync(state)).toBe(true);
    await kit(["add", "beta", "--yes"]);
    const r = await kit(["remove", "beta"], { confirm: [true, true] });
    expect(r.asked).toContain("Delete beta's saved state?");
    expect(existsSync(state)).toBe(false);
  });

  it("rejects modules that are not installed", async () => {
    expect(await kit(["remove", "gamma", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });

  it("validates every scope's plan before applying any (R1)", async () => {
    // alpha lives at project scope, beta at user scope (dev profile). Break the user-scope
    // settings.json so beta's plan can't be staged, and make sure the project scope (which would
    // be applied first) is never touched.
    const userSettings = inHome(ws, ".claude/settings.json");
    expect(existsSync(userSettings)).toBe(true);
    writeFileSync(userSettings, "{ nope");

    const beforeTree = snapshotTree(ws.project);
    const userLockFile = inHome(ws, ".config/harness-kit/lock.json");
    const userLockBefore = readFileSync(userLockFile, "utf8");

    const r = await kit(["remove", "alpha", "beta", "--yes"]);

    expect(r.code).toBe(1);
    expect(r.output).toContain("cannot parse");
    expect(snapshotTree(ws.project)).toEqual(beforeTree);
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha).toBeDefined();
    expect(readFileSync(userLockFile, "utf8")).toBe(userLockBefore);
  });

  it("de-dupes module names before planning (R2)", async () => {
    const r = await kit(["remove", "alpha", "alpha", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("removed from project scope: alpha");
    expect(r.output).not.toContain("alpha, alpha");
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha).toBeUndefined();
  });
});

describe("kit update", () => {
  it("moves to the new version, drops retired contributions, and shows hook diffs", async () => {
    const original = readFileSync(join(ws.publicRepo, "modules/alpha/hooks/check.mjs"), "utf8");
    const sha = releaseAlpha((m) => {
      m.version = "1.1.0";
      m.contributes.hooks = m.contributes.hooks.filter((h: { run: string }) => h.run !== "hooks/start.mjs");
    }, { "hooks/start.mjs": null, "hooks/check.mjs": original + "// v1.1\n" });

    const r = await kit(["update", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("alpha 1.0.0 → 1.1.0");
    expect(r.output).toContain("beta 0.2.0 (up to date)");
    expect(r.output).toContain("+ // v1.1");
    expect(r.output).toContain("- .claude/kit/hooks/alpha/start.mjs");
    expect(existsSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"))).toBe(false);
    expect(readJson(inProject(ws, ".claude/settings.json")).hooks.SessionStart).toBeUndefined();
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.modules.alpha.version).toBe("1.1.0");
    expect(lock.modules.alpha.config.greeting).toBe("hi dev");
    expect(lock.catalogs.public.sha).toBe(sha);
    expect(lock.modules.alpha.scaffolded).toEqual(["docs/context/INDEX.md"]);
  });

  it("never silently discards a user's edit", async () => {
    appendFileSync(inProject(ws, SKILL), "\nMY NOTES\n");
    releaseAlpha((m) => { m.version = "1.1.0"; }, { "skills/alpha-skill/SKILL.md": "---\nname: alpha-skill\ndescription: v1.1\n---\n" });
    const r = await kit(["update", "--yes"]);
    expect(r.output).toContain(`warning: kept your version of ${SKILL}`);
    expect(readFileSync(inProject(ws, SKILL), "utf8")).toContain("MY NOTES");
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.version).toBe("1.1.0");
  });

  it("lets the user choose to take the kit's version", async () => {
    appendFileSync(inProject(ws, SKILL), "\nMY NOTES\n");
    releaseAlpha((m) => { m.version = "1.1.0"; }, { "skills/alpha-skill/SKILL.md": "v1.1 skill\n" });
    const r = await kit(["update", "alpha"], { select: ["overwrite"], confirm: [true] });
    expect(r.asked[0]).toContain("was edited since the kit installed it");
    expect(readFileSync(inProject(ws, SKILL), "utf8")).toBe("v1.1 skill\n");
  });

  it("add stays pinned to the locked catalog commit until update", async () => {
    releaseAlpha((m) => { m.version = "1.1.0"; });
    await kit(["add", "alpha", "--yes"]);
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.version).toBe("1.0.0");
  });

  it("skips modules that left the catalog, and rejects ones that are not installed", async () => {
    const index = join(ws.publicRepo, "catalog.json");
    writeFileSync(index, readFileSync(index, "utf8").replace('"modules/alpha", ', ""));
    commitAll(ws.publicRepo, "drop alpha");
    const r = await kit(["update", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("warning: alpha is no longer in catalog public; skipped");
    expect(await kit(["update", "gamma", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });
});

describe("kit config", () => {
  it("re-prompts with current values and re-renders what depends on them", async () => {
    const r = await kit(["config", "alpha"], { text: ["bonjour", "api"], confirm: [true] });
    expect(r.code).toBe(0);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8")).toContain('Greeting is "bonjour"');
    expect(readJson(inProject(ws, ".claude/kit/config/alpha.json")).values.greeting).toBe("bonjour");
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.config.greeting).toBe("bonjour");
    expect(readFileSync(inProject(ws, "docs/context/INDEX.md"), "utf8")).toContain("Areas: api"); // scaffold untouched
  });

  it("needs exactly one installed module", async () => {
    expect(await kit(["config"])).toMatchObject({ code: 1, output: expect.stringContaining("usage: kit config") });
    expect(await kit(["config", "gamma"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });
});
