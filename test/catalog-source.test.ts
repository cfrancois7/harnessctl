import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fetchCatalog } from "../src/catalog/source.js";
import { commitAll, FIXTURES, git, makeGitCatalog, tempDir } from "./helpers.js";

describe("fetchCatalog", () => {
  it("clones, reports the sha, then follows new commits", () => {
    const repo = makeGitCatalog(FIXTURES.public);
    const cache = tempDir("kit-cache-");
    const first = fetchCatalog({ url: repo }, cache);
    expect(first.sha).toBe(git(repo, "rev-parse", "HEAD"));
    expect(existsSync(join(first.dir, "catalog.json"))).toBe(true);

    writeFileSync(join(repo, "NEW.md"), "new");
    const newSha = commitAll(repo, "second");
    const second = fetchCatalog({ url: repo }, cache);
    expect(second.sha).toBe(newSha);
    expect(second.dir).toBe(first.dir);
    expect(existsSync(join(second.dir, "NEW.md"))).toBe(true);
  });

  it("checks out a pinned sha, and works offline from the cache", () => {
    const repo = makeGitCatalog(FIXTURES.public);
    const cache = tempDir("kit-cache-");
    const pinned = fetchCatalog({ url: repo }, cache).sha;
    writeFileSync(join(repo, "NEW.md"), "new");
    commitAll(repo, "second");
    fetchCatalog({ url: repo }, cache);

    const back = fetchCatalog({ url: repo }, cache, { sha: pinned, offline: true });
    expect(back.sha).toBe(pinned);
    expect(existsSync(join(back.dir, "NEW.md"))).toBe(false);
  });

  it("supports refs (branch and tag) and subdirectories", () => {
    const repo = tempDir("kit-mono-");
    git(repo, "init", "--quiet", "-b", "main");
    writeFileSync(join(repo, "README.md"), "engine");
    commitAll(repo, "engine");
    git(repo, "tag", "v1");
    git(repo, "checkout", "--quiet", "-b", "next");
    writeFileSync(join(repo, "NEXT.md"), "next");
    const nextSha = commitAll(repo, "next");
    const cache = tempDir("kit-cache-");
    expect(fetchCatalog({ url: repo, ref: "next" }, cache).sha).toBe(nextSha);
    expect(existsSync(join(fetchCatalog({ url: repo, ref: "v1" }, cache).dir, "NEXT.md"))).toBe(false);
    expect(() => fetchCatalog({ url: repo, ref: "main", subdir: "catalog" }, cache))
      .toThrowError(/subdirectory "catalog" not found/);
  });

  it("explains failures", () => {
    const cache = tempDir("kit-cache-");
    expect(() => fetchCatalog({ url: join(cache, "does-not-exist") }, cache)).toThrowError(/git clone failed/);
    const repo = makeGitCatalog(FIXTURES.public);
    expect(() => fetchCatalog({ url: repo }, cache, { offline: true })).toThrowError(/not cached.*--offline/);
    expect(() => fetchCatalog({ url: repo, ref: "nope" }, cache)).toThrowError(/ref "nope" not found/);
  });
});
