import { cpSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readUserConfig } from "../src/userconfig.js";
import { runKit } from "./cli-helpers.js";
import { FIXTURES, makeGitCatalog, tempDir } from "./helpers.js";

const REPO_CATALOG = join(import.meta.dirname, "../catalog");
const ctx = () => ({ cwd: tempDir("kit-cwd-"), home: tempDir("kit-home-") });

describe("kit cli basics", () => {
  it("prints usage with --help and with no command", async () => {
    expect((await runKit(["--help"], ctx())).output).toContain("Usage: kit <command>");
    expect(await runKit([], ctx())).toMatchObject({ code: 0 });
  });

  it("fails cleanly on unknown commands, flags and scopes", async () => {
    expect(await runKit(["frobnicate"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining('unknown command "frobnicate"') });
    expect(await runKit(["validate", "--nope"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining("error:") });
    expect(await runKit(["validate", "x", "--scope", "galaxy"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining("--scope must be project or user") });
  });
});

describe("kit validate", () => {
  it("accepts the fixture catalogs and the repo's public catalog", async () => {
    const r = await runKit(["validate", FIXTURES.public], ctx());
    expect(r.code).toBe(0);
    expect(r.output).toContain('catalog "public"');
    expect(r.output).toMatch(/ok\s+alpha@1\.0\.0 \(supported on claude-code\)/);
    expect((await runKit(["validate", REPO_CATALOG], ctx())).code).toBe(0);
  });

  it("notes profile entries that come from another catalog", async () => {
    const r = await runKit(["validate", FIXTURES.company], ctx());
    expect(r.code).toBe(0);
    expect(r.output).toContain('profile industrial: "alpha" is expected from another catalog');
  });

  it("fails on invalid modules and on bad profile config", async () => {
    const dir = tempDir("kit-bad-");
    cpSync(FIXTURES.public, dir, { recursive: true });
    const manifest = join(dir, "modules/beta/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace("hooks/guard.mjs", "hooks/missing.mjs"));
    const profile = join(dir, "profiles/dev.json");
    writeFileSync(profile, readFileSync(profile, "utf8").replace('"hi dev"', "42"));
    const r = await runKit(["validate", dir], ctx());
    expect(r.code).toBe(1);
    expect(r.output).toMatch(/INVALID\s+beta/);
    expect(r.output).toContain("missing hook script hooks/missing.mjs");
    expect(r.output).toContain('profile dev: alpha: config "greeting" must be a string');
  });
});

describe("kit catalog", () => {
  it("adds, lists and removes catalog sources", async () => {
    const c = ctx();
    const repo = makeGitCatalog(FIXTURES.public);
    const added = await runKit(["catalog", "add", repo], c);
    expect(added).toMatchObject({ code: 0, output: expect.stringContaining('added catalog "public" (2 modules, 1 profiles)') });
    expect(readUserConfig(c.home).catalogs).toEqual([{ url: repo }]);
    await runKit(["catalog", "add", repo, "--ref", "main"], c); // same source: replaced, not duplicated
    expect(readUserConfig(c.home).catalogs).toEqual([{ url: repo, ref: "main" }]);
    expect((await runKit(["catalog", "list"], c)).output).toContain(repo);
    expect((await runKit(["catalog", "remove", repo], c)).code).toBe(0);
    expect(readUserConfig(c.home).catalogs).toEqual([]);
    expect((await runKit(["catalog", "remove", repo], c)).code).toBe(1);
  });

  it("does not save a source that is not a catalog", async () => {
    const c = ctx();
    const r = await runKit(["catalog", "add", join(c.cwd, "nowhere")], c);
    expect(r.code).toBe(1);
    expect(readUserConfig(c.home).catalogs).toEqual([]);
  });
});
