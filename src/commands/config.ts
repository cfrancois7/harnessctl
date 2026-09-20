import { resolveModule } from "../catalog/load.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { findInstalled, installModules, loadCatalogs } from "../pipeline.js";
import { promptConfig } from "../prompts.js";

export const configCommand: Command = async (args, env) => {
  const [name, ...rest] = args;
  if (!name || rest.length > 0) throw new KitError("usage: kit config <module> [--scope project|user]");
  const ctx = findInstalled(name, env);
  const locked = ctx.lock.modules[name]!;
  const loaded = loadCatalogs(env, { pin: true });
  const def = resolveModule(loaded.catalogs, `${locked.catalog}:${name}`);
  const config = env.flags.yes ? locked.config : await promptConfig(def, locked.config, env.prompter);
  await installModules([{ def, config, scope: ctx.scope }], loaded, env);
  return 0;
};
