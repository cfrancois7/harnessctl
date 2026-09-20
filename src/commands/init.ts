import { findProfile, resolveModule } from "../catalog/load.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { installModules, loadCatalogs, type InstallItem } from "../pipeline.js";
import { getAdapter } from "../adapters/adapter.js";
import { supportStatus } from "../planner.js";
import { promptConfig } from "../prompts.js";
import type { ModuleDef, Profile, ProfileEntry } from "../types.js";

const refOf = (m: ModuleDef): string => `${m.catalog}:${m.name}`;

export const initCommand: Command = async (_args, env) => {
  const adapter = getAdapter(env.flags.harness);
  const loaded = loadCatalogs(env, { pin: true });
  const profiles = loaded.catalogs.flatMap((c) => c.profiles);

  let profile: Profile | undefined;
  if (env.flags.profile) {
    profile = findProfile(loaded.catalogs, env.flags.profile);
  } else if (env.flags.yes) {
    throw new KitError("--yes needs --profile (or use `kit add <module…>`)");
  } else if (profiles.length > 0) {
    const choice = await env.prompter.select<string | null>("Profile", [
      ...profiles.map((p) => ({ value: p.name as string | null, label: p.name, hint: p.description })),
      { value: null, label: "(none — pick modules manually)" },
    ]);
    profile = choice === null ? undefined : findProfile(loaded.catalogs, choice);
  }

  const entries = new Map<string, ProfileEntry>();
  for (const [ref, entry] of Object.entries(profile?.modules ?? {})) {
    entries.set(refOf(resolveModule(loaded.catalogs, ref)), entry);
  }

  const all = loaded.catalogs.flatMap((c) => c.modules);
  const installable = all.filter((m) => supportStatus(m, adapter).status !== "unsupported");
  for (const m of all.filter((m) => !installable.includes(m))) {
    env.out(`note: ${m.name} is not supported on ${adapter.id} (needs ${supportStatus(m, adapter).missing.join(", ")})`);
  }

  let selected = [...entries.keys()];
  if (!env.flags.yes) {
    selected = await env.prompter.multiselect("Modules to install",
      installable.map((m) => ({ value: refOf(m), label: m.name, hint: `${m.scopes.join("/")} · ${m.description}` })),
      selected);
  }
  if (selected.length === 0) {
    env.out("nothing selected");
    return 0;
  }

  const items: InstallItem[] = [];
  for (const ref of selected) {
    const def = resolveModule(loaded.catalogs, ref);
    const entry = entries.get(ref) ?? {};
    const config = env.flags.yes ? entry.config ?? {} : await promptConfig(def, entry.config ?? {}, env.prompter);
    items.push({ def, config, scope: entry.scope ?? env.flags.scope ?? def.scopes[0]! });
  }
  await installModules(items, loaded, env, profile?.name);
  return 0;
};
