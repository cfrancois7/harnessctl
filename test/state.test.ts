import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { emptyLock, readLock, writeLock } from "../src/lockfile.js";
import { backupRoot, catalogCacheDir, findProjectRoot, lockPath, moduleStateDir } from "../src/paths.js";
import { readUserConfig, sourceKey, writeUserConfig } from "../src/userconfig.js";

const tmp = () => mkdtempSync(join(tmpdir(), "kit-state-"));

describe("paths", () => {
  it("places project state in the repo and user state under ~/.config/harness-kit", () => {
    expect(lockPath("project", "/repo", "/home/u")).toBe("/repo/.harness-kit/lock.json");
    expect(lockPath("user", "/repo", "/home/u")).toBe("/home/u/.config/harness-kit/lock.json");
    expect(backupRoot("project", "/repo", "/home/u")).toBe("/repo/.harness-kit/backup");
    expect(backupRoot("user", "/repo", "/home/u")).toBe("/home/u/.config/harness-kit/backup");
    expect(catalogCacheDir("/home/u")).toBe("/home/u/.cache/harness-kit/catalogs");
    expect(moduleStateDir("/home/u", "budget-guard")).toBe("/home/u/.config/harness-kit/state/budget-guard");
  });

  it("finds the project root from a nested directory", () => {
    const repo = tmp();
    mkdirSync(join(repo, ".git"));
    mkdirSync(join(repo, "src/deep"), { recursive: true });
    expect(findProjectRoot(join(repo, "src/deep"))).toBe(repo);
    const loose = tmp();
    expect(findProjectRoot(loose)).toBe(loose);
  });
});

describe("lockfile", () => {
  it("returns an empty lock when the file is missing", () => {
    expect(readLock(join(tmp(), "lock.json"))).toEqual(emptyLock());
    expect(emptyLock()).toEqual({ lockVersion: 1, harness: "claude-code", catalogs: {}, createdFiles: [], modules: {} });
  });

  it("round-trips and writes a .gitignore next to a project lock", () => {
    const repo = tmp();
    const path = lockPath("project", repo, "/nowhere");
    const lock = { ...emptyLock(), profile: "dev", createdFiles: [".mcp.json"] };
    writeLock(path, lock);
    expect(readLock(path)).toEqual(lock);
    expect(readFileSync(path, "utf8").endsWith("}\n")).toBe(true);
    expect(readFileSync(join(repo, ".harness-kit/.gitignore"), "utf8")).toBe("backup/\n");
  });

  it("does not write a .gitignore for the user lock", () => {
    const home = tmp();
    writeLock(lockPath("user", "/repo", home), emptyLock());
    expect(() => readFileSync(join(home, ".config/harness-kit/.gitignore"))).toThrow();
  });

  it("rejects an unreadable or future lockfile", () => {
    const dir = tmp();
    writeFileSync(join(dir, "bad.json"), "{ nope");
    expect(() => readLock(join(dir, "bad.json"))).toThrowError(/bad\.json/);
    writeFileSync(join(dir, "future.json"), JSON.stringify({ ...emptyLock(), lockVersion: 2 }));
    expect(() => readLock(join(dir, "future.json"))).toThrowError(/lockVersion 2.*newer version of kit/);
  });
});

describe("user config", () => {
  it("defaults to no catalogs and round-trips", () => {
    const home = tmp();
    expect(readUserConfig(home)).toEqual({ catalogs: [] });
    writeUserConfig(home, { catalogs: [{ url: "git@internal:agents/catalog.git", ref: "main" }] });
    expect(readUserConfig(home).catalogs[0]!.url).toBe("git@internal:agents/catalog.git");
  });

  it("identifies a source by url and subdirectory, not ref", () => {
    expect(sourceKey({ url: "u", ref: "main" })).toBe("u#");
    expect(sourceKey({ url: "u", subdir: "catalog" })).toBe("u#catalog");
  });
});
