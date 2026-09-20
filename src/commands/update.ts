import { resolveModule } from "../catalog/load.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { installModules, loadCatalogs, openScope, type InstallItem } from "../pipeline.js";
import { SCOPES } from "../types.js";

export const updateCommand: Command = async (args, env) => {
  const contexts = (env.flags.scope ? [env.flags.scope] : [...SCOPES]).map((scope) => openScope(scope, env));
  for (const name of args) {
    if (!contexts.some((ctx) => ctx.lock.modules[name])) throw new KitError(`module "${name}" is not installed`);
  }
  if (contexts.every((ctx) => Object.keys(ctx.lock.modules).length === 0)) {
    env.out("nothing installed");
    return 0;
  }

  const loaded = loadCatalogs(env, { pin: false });
  const items: InstallItem[] = [];
  for (const ctx of contexts) {
    for (const [name, locked] of Object.entries(ctx.lock.modules)) {
      if (args.length > 0 && !args.includes(name)) continue;
      let def;
      try {
        def = resolveModule(loaded.catalogs, `${locked.catalog}:${name}`);
      } catch (err) {
        if (!(err instanceof KitError)) throw err;
        env.out(`warning: ${name} is no longer in catalog ${locked.catalog}; skipped`);
        continue;
      }
      env.out(def.version === locked.version
        ? `${name} ${locked.version} (up to date)`
        : `${name} ${locked.version} → ${def.version}`);
      const config = Object.fromEntries(Object.entries(locked.config).filter(([key]) => key in def.config));
      items.push({ def, config, scope: ctx.scope });
    }
  }
  await installModules(items, loaded, env);
  return 0;
};
