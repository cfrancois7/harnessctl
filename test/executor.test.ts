import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import { commit, resolveConfined, stage, type Conflict, type ScopeRoot } from "../src/executor.js";
import { hashContent } from "../src/hash.js";
import type { Operation } from "../src/types.js";

let root: string;
let scopeRoot: ScopeRoot;
let backupDir: string;
const read = (rel: string) => readFileSync(join(root, rel), "utf8");
const write = (rel: string, content: string) => {
  mkdirSync(join(root, rel, ".."), { recursive: true });
  writeFileSync(join(root, rel), content);
};
const keep = async () => "keep" as const;
const overwrite = async () => "overwrite" as const;
const opts = (onConflict: (c: Conflict) => Promise<"keep" | "overwrite"> = keep, createdFiles: string[] = []) => ({ scopeRoot, createdFiles, onConflict });

beforeEach(() => {
  root = realpathSync(mkdtempSync(join(tmpdir(), "kit-exec-"))); // macOS: /tmp is a symlink
  scopeRoot = { root, allowed: [""] };
  backupDir = join(root, ".harness-kit/backup/t1");
});

describe("resolveConfined", () => {
  it.each(["../x", "/etc/passwd", "a/../../x", "a\\b", "", "a//b"])("rejects %j", (target) => {
    expect(() => resolveConfined(scopeRoot, target)).toThrowError(KitError);
  });

  it("never lets a module write into .git or the kit's own state directory", () => {
    expect(() => resolveConfined(scopeRoot, ".git/hooks/pre-commit")).toThrowError(/protected directory/);
    expect(() => resolveConfined(scopeRoot, ".harness-kit/lock.json")).toThrowError(/protected directory/);
    expect(resolveConfined(scopeRoot, ".github/workflows/ci.yml")).toBe(join(root, ".github/workflows/ci.yml"));
  });

  it("rejects a symlinked directory that escapes the root", () => {
    const outside = mkdtempSync(join(tmpdir(), "kit-outside-"));
    symlinkSync(outside, join(root, "link"));
    expect(() => resolveConfined(scopeRoot, "link/file.txt")).toThrowError(/symlink/);
  });

  it("enforces allowed prefixes", () => {
    const user: ScopeRoot = { root, allowed: [".claude/", ".claude.json"] };
    expect(resolveConfined(user, ".claude/skills/a/SKILL.md")).toBe(join(root, ".claude/skills/a/SKILL.md"));
    expect(resolveConfined(user, ".claude.json")).toBe(join(root, ".claude.json"));
    expect(() => resolveConfined(user, ".ssh/config")).toThrowError(/outside allowed/);
    expect(() => resolveConfined(user, ".claude.json.bak")).toThrowError(/outside allowed/);
  });
});

describe("stage + commit", () => {
  it("writes new owned files and records their hashes", async () => {
    const ops: Operation[] = [{ kind: "writeOwned", module: "m", target: ".claude/skills/s/SKILL.md", content: "skill" }];
    const staged = await stage(ops, opts());
    expect(existsSync(join(root, ".claude"))).toBe(false); // staging writes nothing
    commit(staged, scopeRoot, backupDir);
    expect(read(".claude/skills/s/SKILL.md")).toBe("skill");
    expect(staged.records.m!.owned.files).toEqual([{ path: ".claude/skills/s/SKILL.md", hash: hashContent("skill") }]);
    expect(existsSync(backupDir)).toBe(false); // nothing pre-existing, nothing to back up
  });

  it("records ownership without writing when content is already identical", async () => {
    write("a.txt", "same");
    const staged = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "same" }], opts());
    expect(staged.writes).toEqual([]);
    expect(staged.records.m!.owned.files).toHaveLength(1);
  });

  it("overwrites an owned, unmodified file without asking", async () => {
    write("a.txt", "v1");
    let asked = false;
    const staged = await stage(
      [{ kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") }],
      opts(async () => { asked = true; return "keep"; }));
    commit(staged, scopeRoot, backupDir);
    expect(asked).toBe(false);
    expect(read("a.txt")).toBe("v2");
    expect(readFileSync(join(backupDir, "a.txt"), "utf8")).toBe("v1");
  });

  it("asks about a user-modified owned file; keep leaves it and warns", async () => {
    write("a.txt", "user edit");
    const seen: Conflict[] = [];
    const staged = await stage(
      [{ kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") }],
      opts(async (c) => { seen.push(c); return "keep"; }));
    expect(seen).toEqual([{ target: "a.txt", reason: "modified", current: "user edit", incoming: "v2" }]);
    expect(staged.writes).toEqual([]);
    expect(staged.warnings).toEqual(["kept your version of a.txt"]);
    expect(staged.records.m!.owned.files).toEqual([{ path: "a.txt", hash: hashContent("v2") }]);
  });

  it("does not take ownership of a pre-existing unowned file that the user keeps", async () => {
    write("a.txt", "theirs");
    const staged = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "ours" }], opts());
    expect(staged.records.m!.owned.files).toEqual([]);
    const forced = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "ours" }], opts(overwrite));
    expect(forced.writes).toEqual([{ target: "a.txt", before: "theirs", after: "ours" }]);
  });

  it("scaffoldOnce creates but never overwrites", async () => {
    write("docs/INDEX.md", "mine");
    const staged = await stage([
      { kind: "scaffoldOnce", module: "m", target: "docs/INDEX.md", content: "template" },
      { kind: "scaffoldOnce", module: "m", target: "docs/roadmap.md", content: "roadmap" },
    ], opts());
    commit(staged, scopeRoot, backupDir);
    expect(read("docs/INDEX.md")).toBe("mine");
    expect(read("docs/roadmap.md")).toBe("roadmap");
    expect(staged.records.m!.scaffolded).toEqual(["docs/roadmap.md"]);
  });

  it("chains several merges into one file and tracks created files", async () => {
    const ops: Operation[] = [
      { kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: { command: "a" } },
      { kind: "mergeJson", module: "n", target: ".mcp.json", path: ["mcpServers", "b"], value: { command: "b" } },
      { kind: "markedBlock", module: "m", target: "CLAUDE.md", id: "m", content: "rules" },
    ];
    const staged = await stage(ops, opts());
    commit(staged, scopeRoot, backupDir);
    expect(Object.keys(JSON.parse(read(".mcp.json")).mcpServers)).toEqual(["a", "b"]);
    expect(staged.createdFiles).toEqual([".mcp.json", "CLAUDE.md"]);
    expect(staged.records.m!.owned.json).toEqual([{ file: ".mcp.json", pointer: "/mcpServers/a" }]);
    expect(staged.records.m!.owned.blocks).toEqual([{ file: "CLAUDE.md", id: "m" }]);
  });

  it("deletes files it created once removals leave them blank, and prunes empty directories", async () => {
    const install: Operation[] = [
      { kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: { command: "a" } },
      { kind: "markedBlock", module: "m", target: "CLAUDE.md", id: "m", content: "rules" },
      { kind: "writeOwned", module: "m", target: ".claude/kit/hooks/m/x.mjs", content: "x" },
    ];
    const first = await stage(install, opts());
    commit(first, scopeRoot, backupDir);
    const removal: Operation[] = [
      { kind: "removeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"] },
      { kind: "removeBlock", module: "m", target: "CLAUDE.md", id: "m" },
      { kind: "deleteOwned", module: "m", target: ".claude/kit/hooks/m/x.mjs", expectedHash: hashContent("x") },
    ];
    const second = await stage(removal, opts(keep, first.createdFiles));
    commit(second, scopeRoot, join(root, ".harness-kit/backup/t2"));
    expect(existsSync(join(root, ".mcp.json"))).toBe(false);
    expect(existsSync(join(root, "CLAUDE.md"))).toBe(false);
    expect(existsSync(join(root, ".claude"))).toBe(false);
    expect(second.createdFiles).toEqual([]);
  });

  it("keeps a blank file the kit did not create", async () => {
    write(".mcp.json", "{}\n");
    const a = await stage([{ kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: 1 }], opts());
    commit(a, scopeRoot, backupDir);
    const b = await stage([{ kind: "removeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"] }], opts(keep, a.createdFiles));
    commit(b, scopeRoot, join(root, ".harness-kit/backup/t2"));
    expect(read(".mcp.json")).toBe("{}\n");
  });

  it("asks before deleting an owned file the user modified", async () => {
    write("a.txt", "user edit");
    const del: Operation[] = [{ kind: "deleteOwned", module: "m", target: "a.txt", expectedHash: hashContent("v1") }];
    expect((await stage(del, opts(keep))).writes).toEqual([]);
    expect((await stage(del, opts(overwrite))).writes).toEqual([{ target: "a.txt", before: "user edit", after: null }]);
  });

  it("aborts the whole plan before writing when a JSON target cannot be parsed", async () => {
    write(".claude/settings.json", "{ broken");
    const ops: Operation[] = [
      { kind: "writeOwned", module: "m", target: "a.txt", content: "a" },
      { kind: "mergeJson", module: "m", target: ".claude/settings.json", path: ["hooks", "Stop"], value: {}, match: { commandContains: "x" } },
    ];
    await expect(stage(ops, opts())).rejects.toThrowError(/cannot parse \.claude\/settings\.json/);
    expect(existsSync(join(root, "a.txt"))).toBe(false);
  });

  it("rolls back every write when one fails", async () => {
    write("a.txt", "v1");
    const staged = await stage([
      { kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") },
      { kind: "writeOwned", module: "m", target: "new/b.txt", content: "b" },
      { kind: "writeOwned", module: "m", target: "c.txt", content: "c" },
    ], opts());
    expect(() => commit(staged, scopeRoot, backupDir, (target) => {
      if (target === "c.txt") throw new Error("disk full");
    })).toThrowError(/disk full/);
    expect(read("a.txt")).toBe("v1");
    expect(existsSync(join(root, "new"))).toBe(false);
    expect(existsSync(join(root, "c.txt"))).toBe(false);
  });

  it("R1: re-reads target before writing and aborts with rollback if it changed on disk since stage()", async () => {
    write("a.txt", "v1");
    const staged = await stage([
      { kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") },
      { kind: "writeOwned", module: "m", target: "c.txt", content: "planned" },
    ], opts());
    let thrown: unknown;
    try {
      commit(staged, scopeRoot, backupDir, (target) => {
        // a.txt is written first; sneak in an external write to c.txt before commit gets to it.
        if (target === "a.txt") writeFileSync(join(root, "c.txt"), "external");
      });
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(KitError);
    expect((thrown as Error).message).toMatch(/c\.txt changed on disk/);
    expect(read("a.txt")).toBe("v1");
    expect(read("c.txt")).toBe("external");
  });

  it("R2: if a restore during rollback fails, throws a KitError naming the original error, the unrestorable targets, and backupDir", async () => {
    write("a.txt", "v1");
    const staged = await stage([
      { kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") },
      { kind: "writeOwned", module: "m", target: "c.txt", content: "c" },
    ], opts());
    let thrown: unknown;
    try {
      commit(staged, scopeRoot, backupDir, (target) => {
        if (target === "c.txt") {
          // Sabotage a.txt's restore path: replace the already-written file with a directory of
          // the same name, so restoring "v1" onto it later fails (rename onto a directory: EISDIR).
          rmSync(join(root, "a.txt"), { force: true, recursive: true });
          mkdirSync(join(root, "a.txt"));
          throw new Error("disk full");
        }
      });
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(KitError);
    const message = (thrown as Error).message;
    expect(message).toMatch(/disk full/);
    expect(message).toMatch(/a\.txt/);
    expect(message).toContain(backupDir);
  });
});
