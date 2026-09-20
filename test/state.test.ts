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

  it("F5: round-trips a full lock and rejects malformed ones, naming the file", () => {
    const dir = tmp();
    const full = {
      lockVersion: 1 as const, harness: "claude-code", profile: "dev",
      catalogs: { public: { url: "git@example:c.git", ref: "main", sha: "0123456789abcdef0123456789abcdef01234567" } },
      createdFiles: [".mcp.json", "CLAUDE.md"],
      modules: {
        alpha: {
          catalog: "public", version: "1.0.0", config: { greeting: "hi", areas: ["api"] },
          owned: {
            files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:a" }],
            json: [{ file: ".mcp.json", pointer: "/mcpServers/alpha-mcp" },
                   { file: ".claude/settings.json", pointer: "/hooks/Stop", match: { commandContains: "x" } }],
            blocks: [{ file: "CLAUDE.md", id: "alpha" }],
          },
          scaffolded: ["docs/context/INDEX.md"],
        },
      },
    };
    const path = join(dir, "lock.json");
    writeLock(path, full);
    expect(readLock(path)).toEqual(full);

    // Partial locks written by older versions of this kit stay readable.
    writeFileSync(join(dir, "partial.json"), JSON.stringify({ lockVersion: 1, harness: "claude-code" }));
    expect(readLock(join(dir, "partial.json"))).toEqual(emptyLock());

    const broken = (name: string, mutate: (lock: typeof full) => void) => {
      const copy = JSON.parse(JSON.stringify(full)) as typeof full;
      mutate(copy);
      const file = join(dir, `${name}.json`);
      writeFileSync(file, JSON.stringify(copy));
      expect(() => readLock(file), name).toThrowError(new RegExp(`${name}\\.json is invalid`));
    };
    broken("key", (l) => { (l.modules as Record<string, unknown>)["../x"] = l.modules.alpha; });
    broken("path", (l) => { l.modules.alpha.owned.files[0]!.path = "../evil"; });
    broken("absolute", (l) => { l.createdFiles[0] = "/etc/passwd"; });
    broken("block", (l) => { l.modules.alpha.owned.blocks[0]!.file = "a/../../b"; });
    broken("pointer", (l) => { l.modules.alpha.owned.json[0]!.pointer = "mcpServers/alpha-mcp"; });
    broken("sha", (l) => { l.catalogs.public.sha = "not-a-sha"; });
    broken("shape", (l) => { (l.modules.alpha as { catalog: unknown }).catalog = 5; });
    broken("owned", (l) => { (l.modules.alpha as { owned: unknown }).owned = "everything"; });

    writeFileSync(join(dir, "list.json"), JSON.stringify([]));
    expect(() => readLock(join(dir, "list.json"))).toThrowError(/list\.json/);
    writeFileSync(join(dir, "null.json"), "null");
    expect(() => readLock(join(dir, "null.json"))).toThrowError(/null\.json/);
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
