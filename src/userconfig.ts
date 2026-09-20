import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { KitError } from "./errors.js";
import { userStateDir } from "./paths.js";
import type { CatalogSource } from "./types.js";

export interface UserConfig { catalogs: CatalogSource[] }

const configPath = (home: string): string => join(userStateDir(home), "config.json");

export const sourceKey = (source: CatalogSource): string => `${source.url}#${source.subdir ?? ""}`;

export function readUserConfig(home: string): UserConfig {
  const path = configPath(home);
  if (!existsSync(path)) return { catalogs: [] };
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as Partial<UserConfig>;
    return { catalogs: raw.catalogs ?? [] };
  } catch (err) {
    throw new KitError(`cannot read ${path}: ${(err as Error).message}`);
  }
}

export function writeUserConfig(home: string, config: UserConfig): void {
  mkdirSync(userStateDir(home), { recursive: true });
  writeFileSync(configPath(home), JSON.stringify(config, null, 2) + "\n", "utf8");
}
