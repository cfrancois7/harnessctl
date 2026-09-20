import { resolve } from "node:path";
import { getAdapter } from "../adapters/adapter.js";
import { loadCatalog } from "../catalog/load.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { resolveConfig, supportStatus } from "../planner.js";

export const validateCommand: Command = async (args, env) => {
  const [path] = args;
  if (!path) throw new KitError("usage: kit validate <catalog-path>");
  const catalog = loadCatalog(resolve(env.cwd, path));
  const adapter = getAdapter(env.flags.harness);
  let problems = catalog.invalid.length;

  env.out(`catalog "${catalog.name}"`);
  for (const m of catalog.modules) {
    env.out(`  ok       ${m.name}@${m.version} (${supportStatus(m, adapter).status} on ${adapter.id})`);
  }
  for (const bad of catalog.invalid) {
    env.out(`  INVALID  ${bad.name}`);
    for (const p of bad.problems) env.out(`           - ${p}`);
  }
  for (const profile of catalog.profiles) {
    for (const [ref, entry] of Object.entries(profile.modules)) {
      const [qualifier, name] = ref.includes(":") ? (ref.split(":", 2) as [string, string]) : [undefined, ref];
      const local = qualifier === undefined || qualifier === catalog.name
        ? catalog.modules.find((m) => m.name === name) : undefined;
      if (!local) {
        if (qualifier === catalog.name || catalog.invalid.some((i) => i.name === name)) {
          problems += 1;
          env.out(`  INVALID  profile ${profile.name}: "${ref}" is not a valid module of this catalog`);
        } else {
          env.out(`  note     profile ${profile.name}: "${ref}" is expected from another catalog`);
        }
        continue;
      }
      try {
        resolveConfig(local, entry.config ?? {});
        if (entry.scope && !local.scopes.includes(entry.scope)) {
          throw new KitError(`${name}: does not support ${entry.scope} scope`);
        }
      } catch (err) {
        if (!(err instanceof KitError)) throw err;
        problems += 1;
        env.out(`  INVALID  profile ${profile.name}: ${err.message}`);
      }
    }
  }
  return problems > 0 ? 1 : 0;
};
