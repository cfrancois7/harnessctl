import { resolveModule } from "../catalog/load.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { installModules, loadCatalogs, type InstallItem } from "../pipeline.js";
import { promptConfig } from "../prompts.js";

export const addCommand: Command = async (args, env) => {
  if (args.length === 0) throw new KitError("usage: kit add <module…> [--scope project|user]");
  const loaded = loadCatalogs(env, { pin: true });
  const items: InstallItem[] = [];
  for (const ref of args) {
    const def = resolveModule(loaded.catalogs, ref);
    const config = env.flags.yes ? {} : await promptConfig(def, {}, env.prompter);
    items.push({ def, config, scope: env.flags.scope ?? def.scopes[0]! });
  }
  await installModules(items, loaded, env);
  return 0;
};
