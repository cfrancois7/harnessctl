import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { KitError } from "./errors.js";
import type { Lockfile } from "./types.js";

export function emptyLock(harness = "claude-code"): Lockfile {
  return { lockVersion: 1, harness, catalogs: {}, createdFiles: [], modules: {} };
}

export function readLock(path: string): Lockfile {
  if (!existsSync(path)) return emptyLock();
  let raw: Partial<Lockfile>;
  try {
    raw = JSON.parse(readFileSync(path, "utf8")) as Partial<Lockfile>;
  } catch (err) {
    throw new KitError(`cannot read lockfile ${path}: ${(err as Error).message}`);
  }
  if (raw.lockVersion !== 1) {
    throw new KitError(`${path} has lockVersion ${String(raw.lockVersion)}; it was written by a newer version of kit`);
  }
  return { ...emptyLock(raw.harness), ...raw } as Lockfile;
}

export function writeLock(path: string, lock: Lockfile): void {
  const dir = dirname(path);
  mkdirSync(dir, { recursive: true });
  const temp = `${path}.kit-tmp`;
  writeFileSync(temp, JSON.stringify(lock, null, 2) + "\n", "utf8");
  renameSync(temp, path);
  const gitignore = join(dir, ".gitignore");
  if (basename(dir) === ".harness-kit" && !existsSync(gitignore)) writeFileSync(gitignore, "backup/\n", "utf8");
}
