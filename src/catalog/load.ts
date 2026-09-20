import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { KitError } from "../errors.js";
import { checkModule, parseCatalogIndex, parseModuleManifest, parseProfile } from "../schema.js";
import type { ModuleDef, Profile } from "../types.js";

export interface Catalog {
  name: string;
  dir: string;
  modules: ModuleDef[];
  profiles: Profile[];
  invalid: { name: string; problems: string[] }[];
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    throw new KitError(`${path}: ${(err as Error).message}`);
  }
}

function readTree(dir: string, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) Object.assign(out, readTree(join(dir, entry.name), rel));
    else if (entry.isFile()) out[rel] = readFileSync(join(dir, entry.name), "utf8");
  }
  return out;
}

export function loadCatalog(dir: string): Catalog {
  const indexPath = join(dir, "catalog.json");
  if (!existsSync(indexPath)) throw new KitError(`no catalog.json in ${dir}`);
  const index = parseCatalogIndex(readJson(indexPath), indexPath);
  const catalog: Catalog = { name: index.name, dir, modules: [], profiles: [], invalid: [] };

  for (const rel of index.modules) {
    const moduleDir = join(dir, rel);
    const fallbackName = basename(rel);
    try {
      if (!existsSync(join(moduleDir, "module.json"))) throw new KitError(`missing ${rel}/module.json`);
      const manifest = parseModuleManifest(readJson(join(moduleDir, "module.json")), `${rel}/module.json`);
      const def: ModuleDef = { ...manifest, catalog: index.name, files: readTree(moduleDir) };
      const problems = checkModule(def);
      if (problems.length > 0) catalog.invalid.push({ name: def.name, problems });
      else catalog.modules.push(def);
    } catch (err) {
      if (!(err instanceof KitError)) throw err;
      catalog.invalid.push({ name: fallbackName, problems: [err.message] });
    }
  }
  for (const rel of index.profiles) {
    catalog.profiles.push({ ...parseProfile(readJson(join(dir, rel)), rel), catalog: index.name });
  }
  return catalog;
}

export function resolveModule(catalogs: Catalog[], ref: string): ModuleDef {
  const [qualifier, name] = ref.includes(":") ? (ref.split(":", 2) as [string, string]) : [undefined, ref];
  const scope = qualifier ? catalogs.filter((c) => c.name === qualifier) : catalogs;
  const hits = scope.flatMap((c) => c.modules.filter((m) => m.name === name));
  if (hits.length === 1) return hits[0]!;
  if (hits.length > 1) {
    throw new KitError(`module "${name}" is ambiguous; use one of: ${hits.map((m) => `${m.catalog}:${m.name}`).join(", ")}`);
  }
  for (const c of scope) {
    const broken = c.invalid.find((i) => i.name === name);
    if (broken) throw new KitError(`module "${name}" in catalog "${c.name}" is invalid:\n  ${broken.problems.join("\n  ")}`);
  }
  throw new KitError(`module "${ref}" not found in catalogs: ${catalogs.map((c) => c.name).join(", ")}`);
}

export function findProfile(catalogs: Catalog[], name: string): Profile {
  const all = catalogs.flatMap((c) => c.profiles);
  const hit = all.find((p) => p.name === name);
  if (!hit) throw new KitError(`profile "${name}" not found; available: ${all.map((p) => p.name).sort().join(", ")}`);
  return hit;
}
