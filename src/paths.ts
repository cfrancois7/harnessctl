import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Scope } from "./types.js";

export function findProjectRoot(cwd: string): string {
  let dir = cwd;
  for (;;) {
    if (existsSync(join(dir, ".harness-kit", "lock.json")) || existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return cwd;
    dir = parent;
  }
}

export const userStateDir = (home: string): string => join(home, ".config", "harness-kit");
export const catalogCacheDir = (home: string): string => join(home, ".cache", "harness-kit", "catalogs");
export const moduleStateDir = (home: string, module: string): string => join(userStateDir(home), "state", module);

const stateDir = (scope: Scope, projectRoot: string, home: string): string =>
  scope === "project" ? join(projectRoot, ".harness-kit") : userStateDir(home);

export const lockPath = (scope: Scope, projectRoot: string, home: string): string =>
  join(stateDir(scope, projectRoot, home), "lock.json");

export const backupRoot = (scope: Scope, projectRoot: string, home: string): string =>
  join(stateDir(scope, projectRoot, home), "backup");
