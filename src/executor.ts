import {
  lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, rmdirSync, rmSync, writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import { KitError } from "./errors.js";
import { hashContent } from "./hash.js";
import { isEmptyJson, removeJsonEntry, toPointer, upsertJsonEntry } from "./ops/json-merge.js";
import { removeBlock, upsertBlock } from "./ops/marked-block.js";
import type { Operation, Owned } from "./types.js";

export interface ScopeRoot { root: string; allowed: string[] }
export interface Conflict { target: string; reason: "modified" | "unowned"; current: string; incoming: string | null }
export interface StageOptions {
  scopeRoot: ScopeRoot;
  createdFiles: string[];
  onConflict: (conflict: Conflict) => Promise<"keep" | "overwrite">;
}
export interface StagedWrite { target: string; before: string | null; after: string | null }
export interface ModuleRecord { owned: Owned; scaffolded: string[] }
export interface Staged {
  writes: StagedWrite[];
  records: Record<string, ModuleRecord>;
  createdFiles: string[];
  warnings: string[];
}

function lstatExists(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

export function resolveConfined(scopeRoot: ScopeRoot, target: string): string {
  const segments = target.split("/");
  if (target === "" || isAbsolute(target) || target.includes("\\") || segments.includes("..") || segments.includes("")) {
    throw new KitError(`unsafe target path: ${JSON.stringify(target)}`);
  }
  if (segments[0] === ".git" || segments[0] === ".harness-kit") {
    throw new KitError(`target inside a protected directory: ${target}`);
  }
  const allowed = scopeRoot.allowed.some((prefix) =>
    prefix === "" || (prefix.endsWith("/") ? target.startsWith(prefix) : target === prefix));
  if (!allowed) throw new KitError(`target outside allowed locations: ${target}`);

  const root = realpathSync(scopeRoot.root);
  const absolute = resolve(root, target);
  let probe = absolute;
  while (!lstatExists(probe)) probe = dirname(probe);
  let real: string;
  try {
    real = realpathSync(probe);
  } catch {
    throw new KitError(`target passes through a broken symlink: ${target}`);
  }
  if (real !== root && !real.startsWith(root + sep)) {
    throw new KitError(`target escapes ${scopeRoot.root} through a symlink: ${target}`);
  }
  return absolute;
}

const isBlank = (target: string, content: string): boolean =>
  target.endsWith(".json") ? isEmptyJson(content) : content.trim() === "";

export async function stage(ops: Operation[], options: StageOptions): Promise<Staged> {
  const state = new Map<string, { before: string | null; current: string | null }>();
  const records: Record<string, ModuleRecord> = {};
  const created = new Set<string>();
  const touchedByRemoval = new Set<string>();
  const warnings: string[] = [];

  const load = (target: string) => {
    let entry = state.get(target);
    if (!entry) {
      const absolute = resolveConfined(options.scopeRoot, target);
      let before: string | null = null;
      if (lstatExists(absolute)) {
        try {
          before = readFileSync(absolute, "utf8");
        } catch (err) {
          throw new KitError(`cannot read ${target}: ${(err as Error).message}`);
        }
      }
      entry = { before, current: before };
      state.set(target, entry);
    }
    return entry;
  };
  const record = (module: string) =>
    (records[module] ??= { owned: { files: [], json: [], blocks: [] }, scaffolded: [] });

  for (const op of ops) {
    const file = load(op.target);
    const rec = record(op.module);
    switch (op.kind) {
      case "writeOwned": {
        const owned = { path: op.target, hash: hashContent(op.content) };
        if (file.current === null || file.current === op.content) {
          file.current = op.content;
          rec.owned.files.push(owned);
        } else if (op.expectedHash !== undefined && hashContent(file.current) === op.expectedHash) {
          file.current = op.content;
          rec.owned.files.push(owned);
        } else {
          const reason = op.expectedHash !== undefined ? "modified" : "unowned";
          const decision = await options.onConflict({ target: op.target, reason, current: file.current, incoming: op.content });
          if (decision === "overwrite") {
            file.current = op.content;
            rec.owned.files.push(owned);
          } else {
            warnings.push(`kept your version of ${op.target}`);
            if (reason === "modified") rec.owned.files.push(owned);
          }
        }
        break;
      }
      case "scaffoldOnce":
        if (file.current === null) {
          file.current = op.content;
          rec.scaffolded.push(op.target);
        }
        break;
      case "mergeJson":
        if (file.current === null) created.add(op.target);
        file.current = upsertJsonEntry(file.current ?? "", op.target, op.path, op.value, op.match);
        rec.owned.json.push({ file: op.target, pointer: toPointer(op.path), ...(op.match ? { match: op.match } : {}) });
        break;
      case "markedBlock":
        if (file.current === null) created.add(op.target);
        file.current = upsertBlock(file.current ?? "", op.id, op.content);
        rec.owned.blocks.push({ file: op.target, id: op.id });
        break;
      case "deleteOwned":
        if (file.current === null) break;
        if (hashContent(file.current) === op.expectedHash) {
          file.current = null;
        } else {
          const decision = await options.onConflict({ target: op.target, reason: "modified", current: file.current, incoming: null });
          if (decision === "overwrite") file.current = null;
          else warnings.push(`kept your version of ${op.target}`);
        }
        break;
      case "removeJson":
        if (file.current !== null) {
          file.current = removeJsonEntry(file.current, op.target, op.path, op.match);
          touchedByRemoval.add(op.target);
        }
        break;
      case "removeBlock":
        if (file.current !== null) {
          file.current = removeBlock(file.current, op.id);
          touchedByRemoval.add(op.target);
        }
        break;
    }
  }

  const createdFiles = new Set([...options.createdFiles, ...created]);
  for (const target of touchedByRemoval) {
    const file = state.get(target)!;
    if (createdFiles.has(target) && file.current !== null && isBlank(target, file.current)) {
      file.current = null;
      createdFiles.delete(target);
    }
  }

  const writes: StagedWrite[] = [];
  for (const [target, file] of state) {
    if (file.before !== file.current) writes.push({ target, before: file.before, after: file.current });
  }
  return { writes, records, createdFiles: [...createdFiles].sort(), warnings };
}

function pruneEmptyDirs(from: string, root: string): void {
  let dir = from;
  while (dir !== root && dir.startsWith(root + sep)) {
    try {
      if (readdirSync(dir).length > 0) return;
      rmdirSync(dir);
    } catch {
      return;
    }
    dir = dirname(dir);
  }
}

function put(absolute: string, content: string | null, root: string): void {
  if (content === null) {
    rmSync(absolute, { force: true });
    pruneEmptyDirs(dirname(absolute), root);
    return;
  }
  mkdirSync(dirname(absolute), { recursive: true });
  const temp = `${absolute}.kit-tmp`;
  writeFileSync(temp, content, "utf8");
  renameSync(temp, absolute);
}

function readCurrent(absolute: string): string | null {
  if (!lstatExists(absolute)) return null;
  return readFileSync(absolute, "utf8");
}

export function commit(staged: Staged, scopeRoot: ScopeRoot, backupDir: string, onWrite?: (target: string) => void): void {
  const root = realpathSync(scopeRoot.root);
  const done: StagedWrite[] = [];
  try {
    for (const w of staged.writes) {
      const absolute = resolveConfined(scopeRoot, w.target);
      // R1: re-read before write (optimistic concurrency). Files such as ~/.claude.json can be
      // rewritten by the harness itself, and the user confirms the plan between stage() and
      // commit(), so re-check the target still matches what the plan was computed from.
      const onDisk = readCurrent(absolute);
      if (onDisk !== w.before) {
        throw new KitError(`${w.target} changed on disk after the plan was computed; nothing was changed — run the command again`);
      }
      if (w.before !== null) {
        const backup = join(backupDir, w.target);
        mkdirSync(dirname(backup), { recursive: true });
        writeFileSync(backup, w.before, "utf8");
      }
      onWrite?.(w.target);
      done.push(w);
      put(absolute, w.after, root);
    }
  } catch (err) {
    // R2: rollback must not mask the original error. Try every restore even if one fails, so a
    // broken restore never leaves other files un-rolled-back; only report restore failures
    // separately from (and without hiding) the error that triggered the rollback.
    const failed: string[] = [];
    for (const w of done.reverse()) {
      try {
        put(resolve(root, w.target), w.before, root);
      } catch {
        failed.push(w.target);
      }
    }
    if (failed.length > 0) {
      throw new KitError(
        `${(err as Error).message}; additionally, rollback could not restore: ${failed.join(", ")} (originals saved in ${backupDir})`,
      );
    }
    throw err;
  }
}
