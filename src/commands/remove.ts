import { existsSync, rmSync } from "node:fs";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { writeLock } from "../lockfile.js";
import { moduleStateDir } from "../paths.js";
import { applyPlan, findInstalled, validatePlan, type ScopeContext } from "../pipeline.js";
import { planRemove } from "../planner.js";

export const removeCommand: Command = async (args, env) => {
  if (args.length === 0) throw new KitError("usage: kit remove <module…> [--scope project|user]");
  const names = [...new Set(args)];
  const groups = new Map<string, { ctx: ScopeContext; names: string[] }>();
  for (const name of names) {
    const ctx = findInstalled(name, env);
    const group = groups.get(ctx.scope) ?? { ctx, names: [] };
    group.names.push(name);
    groups.set(ctx.scope, group);
  }

  // Compute and validate every scope's removal plan before applying any of them: scopes are
  // applied one at a time below, so without this pass an error knowable up front in a later
  // scope's plan (e.g. an unparseable settings file) would surface only after an earlier scope
  // had already been removed and its lock rewritten.
  const plans = [...groups.values()].map((group) => ({ ...group, ops: planRemove(group.names, group.ctx.lock) }));
  for (const { ctx, ops } of plans) await validatePlan(ctx, ops);

  for (const { ctx, names: groupNames, ops } of plans) {
    const staged = await applyPlan(ctx, ops, env);
    if (!staged) continue;
    const left = groupNames.flatMap((name) => ctx.lock.modules[name]!.scaffolded);
    for (const name of groupNames) delete ctx.lock.modules[name];
    const usedCatalogs = new Set(Object.values(ctx.lock.modules).map((m) => m.catalog));
    for (const catalog of Object.keys(ctx.lock.catalogs)) {
      if (!usedCatalogs.has(catalog)) delete ctx.lock.catalogs[catalog];
    }
    if (Object.keys(ctx.lock.modules).length === 0) delete ctx.lock.profile;
    ctx.lock.createdFiles = staged.createdFiles;
    writeLock(ctx.lockFile, ctx.lock);
    env.out(`  removed from ${ctx.scope} scope: ${groupNames.join(", ")}`);
    if (left.length > 0) env.out(`  left in place (yours now): ${left.join(", ")}`);

    for (const name of groupNames) {
      const state = moduleStateDir(env.home, name);
      if (!existsSync(state)) continue;
      if (!env.flags.yes && (await env.prompter.confirm(`Delete ${name}'s saved state?`, false))) {
        rmSync(state, { recursive: true, force: true });
      } else {
        env.out(`  kept saved state in ${state}`);
      }
    }
  }
  return 0;
};
