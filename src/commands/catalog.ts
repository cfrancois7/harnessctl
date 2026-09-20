import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { loadCatalog } from "../catalog/load.js";
import { fetchCatalog } from "../catalog/source.js";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { catalogCacheDir } from "../paths.js";
import type { CatalogSource } from "../types.js";
import { readUserConfig, sourceKey, writeUserConfig } from "../userconfig.js";

const USAGE = "usage: kit catalog list | add <git-url> [--ref R] [--subdir D] | remove <git-url>";

export const catalogCommand: Command = async (args, env) => {
  const [action = "list", url] = args;
  const config = readUserConfig(env.home);

  if (action === "list") {
    if (config.catalogs.length === 0) env.out("no catalogs configured");
    for (const c of config.catalogs) {
      env.out(`${c.url}${c.ref ? ` @${c.ref}` : ""}${c.subdir ? ` /${c.subdir}` : ""}`);
    }
    return 0;
  }
  if ((action !== "add" && action !== "remove") || !url) throw new KitError(USAGE);
  // A local path is stored absolute so it works from any directory.
  const resolvedUrl = existsSync(resolve(env.cwd, url)) ? resolve(env.cwd, url) : url;

  if (action === "remove") {
    const kept = config.catalogs.filter((c) => c.url !== resolvedUrl);
    if (kept.length === config.catalogs.length) throw new KitError(`catalog ${resolvedUrl} is not configured`);
    writeUserConfig(env.home, { catalogs: kept });
    env.out(`removed catalog ${resolvedUrl}`);
    return 0;
  }

  const source: CatalogSource = {
    url: resolvedUrl,
    ...(env.flags.ref ? { ref: env.flags.ref } : {}),
    ...(env.flags.subdir ? { subdir: env.flags.subdir } : {}),
  };
  // Fetch and load before saving, so a bad URL never lands in the config.
  const fetched = fetchCatalog(source, catalogCacheDir(env.home), { offline: env.flags.offline });
  const catalog = loadCatalog(fetched.dir);
  writeUserConfig(env.home, {
    catalogs: [...config.catalogs.filter((c) => sourceKey(c) !== sourceKey(source)), source],
  });
  env.out(`added catalog "${catalog.name}" (${catalog.modules.length} modules, ${catalog.profiles.length} profiles)`);
  return 0;
};
