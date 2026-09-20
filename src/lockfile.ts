import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { z } from "zod";
import { KitError } from "./errors.js";
import { parseSchema, relPath } from "./schema.js";
import type { Lockfile } from "./types.js";

// The project lock is committed and hand-merged, so it is only semi-trusted: module names and
// owned paths from it reach the filesystem (removal of a module's state directory, writes inside a
// scope root). Validate the shape here rather than letting a raw TypeError escape later.
const ownedSchema = z.object({
  files: z.array(z.object({ path: relPath, hash: z.string().min(1) })).default([]),
  json: z.array(z.object({
    file: relPath,
    pointer: z.string().startsWith("/"),
    match: z.object({ commandContains: z.string() }).optional(),
  })).default([]),
  blocks: z.array(z.object({ file: relPath, id: z.string().min(1) })).default([]),
}).default({});

// Key order matters: zod rebuilds the object in schema order, and writeLock serialises it again.
// This order is the one emptyLock/installModules produce, so a lock this kit wrote round-trips
// byte-identically instead of being reshuffled on the next command.
const lockSchema = z.object({
  lockVersion: z.literal(1),
  harness: z.string().min(1).default("claude-code"),
  catalogs: z.record(z.object({
    url: z.string().min(1),
    ref: z.string().optional(),
    subdir: z.string().optional(),
    sha: z.string().regex(/^[0-9a-f]{7,40}$/, "must be a git object id"),
  })).default({}),
  createdFiles: z.array(relPath).default([]),
  modules: z.record(
    z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "lowercase letters, digits and dashes"),
    z.object({
      catalog: z.string().min(1),
      version: z.string().min(1),
      config: z.record(z.unknown()).default({}),
      owned: ownedSchema,
      scaffolded: z.array(relPath).default([]),
    }),
  ).default({}),
  profile: z.string().optional(),
});

export function emptyLock(harness = "claude-code"): Lockfile {
  return { lockVersion: 1, harness, catalogs: {}, createdFiles: [], modules: {} };
}

export function readLock(path: string): Lockfile {
  if (!existsSync(path)) return emptyLock();
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    throw new KitError(`cannot read lockfile ${path}: ${(err as Error).message}`);
  }
  const version = (raw as { lockVersion?: unknown } | null)?.lockVersion;
  if (version !== undefined && version !== 1) {
    throw new KitError(`${path} has lockVersion ${String(version)}; it was written by a newer version of kit`);
  }
  return parseSchema(lockSchema, raw, path) as Lockfile;
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
