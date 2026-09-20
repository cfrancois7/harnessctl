import { join } from "node:path";
import { getAdapter, type HarnessAdapter } from "./adapters/adapter.js";
import { loadCatalog, type Catalog } from "./catalog/load.js";
import { fetchCatalog } from "./catalog/source.js";
import { lineDiff } from "./diff.js";
import type { Env } from "./env.js";
import { KitError } from "./errors.js";
import { commit, stage, type Conflict, type ScopeRoot, type Staged } from "./executor.js";
import { readLock, writeLock } from "./lockfile.js";
import { backupRoot, catalogCacheDir, findProjectRoot, lockPath } from "./paths.js";
import { planModule, resolveConfig, supportStatus } from "./planner.js";
import { SCOPES, type CatalogLock, type CatalogSource, type Lockfile, type ModuleDef, type Operation, type Scope } from "./types.js";
import { readUserConfig, sourceKey } from "./userconfig.js";

export interface LoadedCatalogs { catalogs: Catalog[]; locks: Record<string, CatalogLock> }

export function loadCatalogs(env: Env, options: { pin: boolean }): LoadedCatalogs {
  const projectRoot = findProjectRoot(env.cwd);
  const wanted = new Map<string, { source: CatalogSource; sha?: string }>();
  const want = (source: CatalogSource, sha?: string) => {
    if (!wanted.has(sourceKey(source))) wanted.set(sourceKey(source), { source, sha });
  };
  for (const scope of SCOPES) {
    for (const { sha, ...source } of Object.values(readLock(lockPath(scope, projectRoot, env.home)).catalogs)) {
      want(source, sha);
    }
  }
  for (const source of readUserConfig(env.home).catalogs) want(source);
  for (const url of env.flags.catalog) {
    want({ url, ...(env.flags.ref ? { ref: env.flags.ref } : {}), ...(env.flags.subdir ? { subdir: env.flags.subdir } : {}) });
  }
  if (wanted.size === 0) {
    throw new KitError("no catalogs configured; run `kit catalog add <git-url>` or pass --catalog <git-url>");
  }

  const loaded: LoadedCatalogs = { catalogs: [], locks: {} };
  for (const { source, sha } of wanted.values()) {
    const fetched = fetchCatalog(source, catalogCacheDir(env.home),
      { offline: env.flags.offline, ...(options.pin && sha ? { sha } : {}) });
    const catalog = loadCatalog(fetched.dir);
    if (loaded.locks[catalog.name]) {
      throw new KitError(`two catalogs are both named "${catalog.name}": ${loaded.locks[catalog.name]!.url} and ${source.url}`);
    }
    loaded.catalogs.push(catalog);
    loaded.locks[catalog.name] = { ...source, sha: fetched.sha };
    for (const bad of catalog.invalid) {
      env.out(`warning: skipping invalid module ${catalog.name}:${bad.name} (${bad.problems.length} problem(s); run kit validate)`);
    }
  }
  return loaded;
}

export function loadCatalogsWithFallback(env: Env): LoadedCatalogs | null {
  try {
    return loadCatalogs(env, { pin: false });
  } catch (err) {
    if (!(err instanceof KitError)) throw err;
    env.out(`warning: ${err.message}`);
  }
  try {
    const offline = loadCatalogs({ ...env, flags: { ...env.flags, offline: true } }, { pin: false });
    env.out("warning: using cached catalogs");
    return offline;
  } catch (err) {
    if (!(err instanceof KitError)) throw err;
    return null;
  }
}

export interface ScopeContext {
  scope: Scope;
  adapter: HarnessAdapter;
  scopeRoot: ScopeRoot;
  lockFile: string;
  backupDir: string;
  lock: Lockfile;
}

export function openScope(scope: Scope, env: Env): ScopeContext {
  const projectRoot = findProjectRoot(env.cwd);
  const adapter = getAdapter(env.flags.harness);
  const lockFile = lockPath(scope, projectRoot, env.home);
  const lock = readLock(lockFile);
  if (Object.keys(lock.modules).length > 0 && lock.harness !== adapter.id) {
    throw new KitError(`${lockFile} was written for harness "${lock.harness}", not "${adapter.id}"`);
  }
  lock.harness = adapter.id;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return {
    scope, adapter, lockFile, lock,
    scopeRoot: { root: scope === "project" ? projectRoot : env.home, allowed: adapter.allowedPrefixes(scope) },
    backupDir: join(backupRoot(scope, projectRoot, env.home), stamp),
  };
}

export function findInstalled(name: string, env: Env): ScopeContext {
  const scopes = (env.flags.scope ? [env.flags.scope] : [...SCOPES]).map((s) => openScope(s, env));
  const hits = scopes.filter((ctx) => ctx.lock.modules[name]);
  if (hits.length === 0) throw new KitError(`module "${name}" is not installed`);
  if (hits.length > 1) throw new KitError(`module "${name}" is installed at project and user scope; pass --scope`);
  return hits[0]!;
}

const isHookCode = (target: string): boolean => target.includes("/kit/hooks/") || target.endsWith("/kit/runtime.mjs");

export async function applyPlan(ctx: ScopeContext, ops: Operation[], env: Env): Promise<Staged | null> {
  const onConflict = async (c: Conflict): Promise<"keep" | "overwrite"> => {
    if (env.flags.yes) return "keep";
    if (c.incoming !== null) for (const line of lineDiff(c.current, c.incoming)) env.out(`    ${line}`);
    const why = c.reason === "modified" ? "was edited since the kit installed it" : "already exists and is not managed by the kit";
    return env.prompter.select(`${c.target} ${why}`, [
      { value: "keep" as const, label: "Keep my version" },
      { value: "overwrite" as const, label: c.incoming === null ? "Delete it" : "Replace it with the kit's version" },
    ], "keep" as const);
  };
  const staged = await stage(ops, { scopeRoot: ctx.scopeRoot, createdFiles: ctx.lock.createdFiles, onConflict });

  env.out(`${ctx.scope} scope (${ctx.scopeRoot.root}):`);
  if (staged.writes.length === 0) env.out("  (no file changes)");
  for (const w of staged.writes) {
    env.out(`  ${w.before === null ? "+" : w.after === null ? "-" : "~"} ${w.target}`);
    if (isHookCode(w.target) && w.before !== null && w.after !== null) {
      for (const line of lineDiff(w.before, w.after)) env.out(`      ${line}`);
    }
  }
  if (staged.writes.some((w) => w.target === ".claude.json")) {
    env.out("  note: ~/.claude.json is also written by Claude Code; close running sessions before applying");
  }
  for (const warning of staged.warnings) env.out(`  warning: ${warning}`);

  if (env.flags.dryRun) {
    env.out("  dry run: nothing written");
    return null;
  }
  if (!env.flags.yes && staged.writes.length > 0
      && !(await env.prompter.confirm(`Apply these changes to ${ctx.scope} scope?`, true))) {
    env.out("  skipped");
    return null;
  }
  commit(staged, ctx.scopeRoot, ctx.backupDir);
  return staged;
}

export interface InstallItem { def: ModuleDef; config: Record<string, unknown>; scope: Scope }

const opsForGroup = (group: InstallItem[], scope: Scope, ctx: ScopeContext, env: Env): Operation[] =>
  group.flatMap((item) =>
    planModule({ def: item.def, config: item.config }, scope, ctx.adapter, { home: env.home }, ctx.lock));

/**
 * Validate a scope's plan without writing anything: stages the ops in memory (auto-"keep" on any
 * conflict, result discarded) purely to surface errors that are knowable up front (an unparseable
 * settings file, a confinement violation, ...) — no prompts, no output, no writes. Callers that
 * apply several scopes in sequence should call this for every scope before applying any of them,
 * so a problem in a later scope aborts before an earlier scope is committed and locked.
 */
export async function validatePlan(ctx: ScopeContext, ops: Operation[]): Promise<void> {
  await stage(ops, { scopeRoot: ctx.scopeRoot, createdFiles: ctx.lock.createdFiles, onConflict: async () => "keep" });
}

export async function installModules(
  items: InstallItem[], loaded: LoadedCatalogs, env: Env, profile?: string,
): Promise<void> {
  // Validate every scope's plan before writing anything. Scopes are applied one at a time below,
  // so without this pass a problem that's knowable up front in a later scope (an unsupported
  // capability/scope, an unparseable settings file, a confinement violation, ...) would surface
  // only after an earlier scope had already been committed and locked.
  for (const scope of SCOPES) {
    const group = items.filter((item) => item.scope === scope);
    if (group.length === 0) continue;
    const ctx = openScope(scope, env);
    await validatePlan(ctx, opsForGroup(group, scope, ctx, env));
  }

  for (const scope of SCOPES) {
    const group = items.filter((item) => item.scope === scope);
    if (group.length === 0) continue;
    const ctx = openScope(scope, env);
    const ops = opsForGroup(group, scope, ctx, env);
    for (const item of group) {
      const support = supportStatus(item.def, ctx.adapter);
      if (support.status === "degraded") {
        env.out(`note: ${item.def.name} runs degraded on ${ctx.adapter.id}; unavailable: ${support.missing.join(", ")}`);
      }
    }
    const staged = await applyPlan(ctx, ops, env);
    if (!staged) continue;

    const rehashed = new Map<string, string>();
    for (const item of group) {
      const record = staged.records[item.def.name] ?? { owned: { files: [], json: [], blocks: [] }, scaffolded: [] };
      for (const file of record.owned.files) rehashed.set(file.path, file.hash);
      const previous = ctx.lock.modules[item.def.name];
      ctx.lock.modules[item.def.name] = {
        catalog: item.def.catalog,
        version: item.def.version,
        config: resolveConfig(item.def, item.config),
        owned: record.owned,
        scaffolded: [...new Set([...(previous?.scaffolded ?? []), ...record.scaffolded])].sort(),
      };
      ctx.lock.catalogs[item.def.catalog] = loaded.locks[item.def.catalog]!;
    }
    // Shared files (the runtime shim, ...) are written once but owned by several modules. Only the
    // modules installed in this run recorded the new hash; without this, every other owner keeps a
    // stale hash and `kit status` reports the shared file as modified for them.
    for (const locked of Object.values(ctx.lock.modules)) {
      for (const file of locked.owned.files) {
        const hash = rehashed.get(file.path);
        if (hash !== undefined) file.hash = hash;
      }
    }
    ctx.lock.createdFiles = staged.createdFiles;
    if (profile && scope === "project") ctx.lock.profile = profile;
    writeLock(ctx.lockFile, ctx.lock);
    env.out(`  installed at ${scope} scope: ${group.map((i) => `${i.def.name}@${i.def.version}`).join(", ")}`);
  }
}
