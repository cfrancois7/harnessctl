import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { getAdapter, type HarnessAdapter } from "../src/adapters/adapter.js";
import { loadCatalog, resolveModule } from "../src/catalog/load.js";
import { emptyLock } from "../src/lockfile.js";
import { impliedCapabilities, planModule, planRemove, resolveConfig, supportStatus } from "../src/planner.js";
import type { Lockfile, ModuleLock } from "../src/types.js";

const catalogs = [loadCatalog(join(import.meta.dirname, "fixtures/catalog"))];
const alpha = resolveModule(catalogs, "alpha");
const beta = resolveModule(catalogs, "beta");
const claude = getAdapter("claude-code");
const env = { home: "/home/u" };
const limited: HarnessAdapter = { ...claude, id: "limited", capabilities: () => ["skills", "instructions", "mcp"] };

const moduleLock = (owned: Partial<ModuleLock["owned"]>): ModuleLock => ({
  catalog: "public", version: "0.9.0", config: {}, scaffolded: [],
  owned: { files: [], json: [], blocks: [], ...owned },
});

describe("capabilities", () => {
  it("derives capabilities from contributions", () => {
    expect(impliedCapabilities(alpha).sort()).toEqual(
      ["instructions", "mcp", "pre-tool-hook", "session-hook", "skills"]);
    expect(impliedCapabilities(beta).sort()).toEqual(["pre-tool-hook", "subagent-intercept"]);
  });

  it("classifies support", () => {
    expect(supportStatus(alpha, claude)).toEqual({ status: "supported", missing: [] });
    expect(supportStatus(alpha, limited)).toEqual({ status: "unsupported", missing: ["pre-tool-hook", "session-hook"] });
    const wantsStatusline = { ...alpha,
      requires: { capabilities: [], optional: ["statusline" as const], env: [] },
      contributes: { ...alpha.contributes, hooks: [] } };
    expect(supportStatus(wantsStatusline, limited)).toEqual({ status: "degraded", missing: ["statusline"] });
  });

  it("refuses an unsupported module before producing any operation", () => {
    expect(() => planModule({ def: beta, config: {} }, "user", limited, env, emptyLock()))
      .toThrowError(/module "beta" needs capabilities that limited lacks: pre-tool-hook, subagent-intercept/);
  });

  it("refuses a scope the module does not support", () => {
    expect(() => planModule({ def: alpha, config: {} }, "user", claude, env, emptyLock()))
      .toThrowError(/module "alpha" does not support user scope \(supports: project\)/);
  });
});

describe("resolveConfig", () => {
  it("applies defaults and keeps provided values", () => {
    expect(resolveConfig(alpha, { greeting: "yo" })).toEqual({ greeting: "yo", areas: ["api"] });
  });

  it("rejects wrong types, unknown keys and missing values", () => {
    expect(() => resolveConfig(alpha, { greeting: 5 })).toThrowError(/alpha: config "greeting" must be a string/);
    expect(() => resolveConfig(alpha, { nope: 1 })).toThrowError(/alpha: unknown config "nope"/);
    expect(() => resolveConfig(beta, { mode: "loud" })).toThrowError(/one of warn, block/);
    const noDefault = { ...alpha, config: { token: { type: "string" as const } } };
    expect(() => resolveConfig(noDefault, {})).toThrowError(/alpha: config "token" has no value/);
  });
});

describe("planModule", () => {
  it("is the adapter's operations on a fresh install", () => {
    const ops = planModule({ def: alpha, config: { greeting: "hi" } }, "project", claude, env, emptyLock());
    expect(ops).toEqual(claude.translate(alpha, { greeting: "hi", areas: ["api"] }, "project", env));
  });

  it("on update, carries expected hashes and removes what the new version no longer produces", () => {
    const lock: Lockfile = { ...emptyLock(), modules: { alpha: moduleLock({
      files: [{ path: ".claude/skills/alpha-skill/SKILL.md", hash: "sha256:old" },
              { path: ".claude/kit/hooks/alpha/retired.mjs", hash: "sha256:gone" }],
      json: [{ file: ".claude/settings.json", pointer: "/hooks/Stop", match: { commandContains: "kit/hooks/alpha/retired.mjs" } },
             { file: ".mcp.json", pointer: "/mcpServers/alpha-mcp" }],
      blocks: [{ file: "CLAUDE.md", id: "alpha" }, { file: "AGENTS.md", id: "alpha" }],
    }) } };
    const ops = planModule({ def: alpha, config: {} }, "project", claude, env, lock);
    expect(ops.slice(0, 3)).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/hooks/alpha/retired.mjs", expectedHash: "sha256:gone" },
      { kind: "removeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "Stop"],
        match: { commandContains: "kit/hooks/alpha/retired.mjs" } },
      { kind: "removeBlock", module: "alpha", target: "AGENTS.md", id: "alpha" },
    ]);
    const skill = ops.find((o) => o.kind === "writeOwned" && o.target.endsWith("SKILL.md"));
    expect(skill).toMatchObject({ expectedHash: "sha256:old" });
  });

  it("finds the expected hash of a shared file owned by another module", () => {
    const lock: Lockfile = { ...emptyLock(), modules: { beta: moduleLock({
      files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }] }) } };
    const ops = planModule({ def: alpha, config: {} }, "project", claude, env, lock);
    expect(ops.find((o) => o.target === ".claude/kit/runtime.mjs")).toMatchObject({ expectedHash: "sha256:rt" });
  });
});

describe("planRemove", () => {
  const lock: Lockfile = { ...emptyLock(), modules: {
    alpha: moduleLock({
      files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }, { path: ".claude/kit/hooks/alpha/check.mjs", hash: "sha256:c" }],
      json: [{ file: ".mcp.json", pointer: "/mcpServers/alpha-mcp" }],
      blocks: [{ file: "CLAUDE.md", id: "alpha" }] }),
    beta: moduleLock({ files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }] }),
  } };

  it("inverts what the lock records, keeping files other modules still own", () => {
    expect(planRemove(["alpha"], lock)).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/hooks/alpha/check.mjs", expectedHash: "sha256:c" },
      { kind: "removeJson", module: "alpha", target: ".mcp.json", path: ["mcpServers", "alpha-mcp"] },
      { kind: "removeBlock", module: "alpha", target: "CLAUDE.md", id: "alpha" },
    ]);
  });

  it("deletes the shared file when the last owner goes", () => {
    const onlyBeta: Lockfile = { ...lock, modules: { beta: lock.modules.beta! } };
    expect(planRemove(["beta"], onlyBeta)).toEqual([
      { kind: "deleteOwned", module: "beta", target: ".claude/kit/runtime.mjs", expectedHash: "sha256:rt" }]);
  });

  it("deletes a shared file exactly once when all its owners are removed together", () => {
    const runtimeDeletes = planRemove(["alpha", "beta"], lock)
      .filter((o) => o.kind === "deleteOwned" && o.target === ".claude/kit/runtime.mjs");
    expect(runtimeDeletes).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/runtime.mjs", expectedHash: "sha256:rt" }]);
  });

  it("rejects a module that is not installed", () => {
    expect(() => planRemove(["nope"], lock)).toThrowError(/module "nope" is not installed/);
  });
});
