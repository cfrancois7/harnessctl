import { KitError } from "./errors.js";

const PLACEHOLDER = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g;

export function listPlaceholders(text: string): string[] {
  return [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1] as string))];
}

export function renderTemplate(text: string, vars: Record<string, string>, where: string): string {
  return text.replace(PLACEHOLDER, (_whole, key: string) => {
    const value = vars[key];
    if (value === undefined) throw new KitError(`${where}: unknown placeholder {{${key}}}`);
    return value;
  });
}

export function templateVars(
  manifest: { name: string; version: string },
  config: Record<string, unknown>,
): Record<string, string> {
  const vars: Record<string, string> = {
    "module.name": manifest.name,
    "module.version": manifest.version,
  };
  for (const [key, value] of Object.entries(config)) {
    vars[`config.${key}`] = Array.isArray(value) ? value.join(", ") : String(value);
  }
  return vars;
}

export function knownPlaceholders(manifest: { config: Record<string, unknown> }): string[] {
  return ["module.name", "module.version", ...Object.keys(manifest.config).map((k) => `config.${k}`)];
}
