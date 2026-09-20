import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const FIXTURES = {
  public: join(import.meta.dirname, "fixtures/catalog"),
  company: join(import.meta.dirname, "fixtures/company-catalog"),
};

/** A fresh temp directory, realpath'd (on macOS /tmp is a symlink). */
export function tempDir(prefix = "kit-"): string {
  return realpathSync(mkdtempSync(join(tmpdir(), prefix)));
}

export function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=kit-test", "-c", "user.email=kit@test.invalid", ...args],
    { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

export function commitAll(repo: string, message: string): string {
  git(repo, "add", "-A");
  git(repo, "commit", "--quiet", "-m", message);
  return git(repo, "rev-parse", "HEAD");
}

export function makeGitCatalog(fixtureDir: string): string {
  const repo = tempDir("kit-catalog-");
  cpSync(fixtureDir, repo, { recursive: true });
  git(repo, "init", "--quiet", "-b", "main");
  commitAll(repo, "initial catalog");
  return repo;
}

export function snapshotTree(root: string, exclude: string[] = []): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (rel === ".git" || exclude.some((e) => rel === e || rel.startsWith(e + "/"))) continue;
      if (entry.isDirectory()) walk(join(dir, entry.name), rel);
      else out[rel] = readFileSync(join(dir, entry.name), "utf8");
    }
  };
  walk(root, "");
  return out;
}
