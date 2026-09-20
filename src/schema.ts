import { z } from "zod";
import { KitError } from "./errors.js";
import { knownPlaceholders, listPlaceholders } from "./template.js";
import {
  CAPABILITIES, CONFIG_TYPES, HOOK_EVENTS, SCOPES, TOOL_MATCHERS,
  type ConfigField, type ModuleDef, type ModuleManifest, type Profile,
} from "./types.js";

/** A path that can safely be resolved inside a scope root. Shared with the lockfile schema. */
export const relPath = z.string().min(1).refine(
  (p) => !p.startsWith("/") && !p.includes("\\")
    && !p.split("/").some((segment) => segment === "" || segment === "." || segment === ".."),
  "must be a relative POSIX path without '.' or '..' segments",
);

const configField = z.object({
  type: z.enum(CONFIG_TYPES),
  default: z.unknown().optional(),
  prompt: z.string().optional(),
  values: z.array(z.string()).optional(),
}).strict();

const hook = z.object({
  event: z.enum(HOOK_EVENTS),
  match: z.object({ tool: z.enum(TOOL_MATCHERS) }).strict().optional(),
  run: relPath.refine((p) => p.startsWith("hooks/"), "must be under hooks/"),
  onError: z.enum(["allow", "deny"]).default("allow"),
}).strict();

const moduleSchema = z.object({
  name: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "lowercase letters, digits and dashes"),
  version: z.string().regex(/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/, "semver"),
  description: z.string().default(""),
  scopes: z.array(z.enum(SCOPES)).min(1),
  requires: z.object({
    capabilities: z.array(z.enum(CAPABILITIES)).default([]),
    optional: z.array(z.enum(CAPABILITIES)).default([]),
    env: z.array(z.string()).default([]),
  }).strict().default({}),
  config: z.record(configField).default({}),
  contributes: z.object({
    skills: z.array(relPath).default([]),
    hooks: z.array(hook).default([]),
    instructions: z.array(relPath).default([]),
    mcpServers: z.record(z.unknown()).default({}),
    scaffold: z.array(z.object({ from: relPath, to: relPath }).strict()).default([]),
  }).strict().default({}),
}).strict();

const profileSchema = z.object({
  name: z.string().min(1),
  description: z.string().default(""),
  modules: z.record(z.object({
    scope: z.enum(SCOPES).optional(),
    config: z.record(z.unknown()).optional(),
  }).strict()),
}).strict();

const catalogIndexSchema = z.object({
  name: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
  modules: z.array(relPath).default([]),
  profiles: z.array(relPath).default([]),
}).strict();

/** Parse `raw`, or throw a KitError listing every problem. Shared with the lockfile schema. */
export function parseSchema<T>(schema: z.ZodType<T, z.ZodTypeDef, unknown>, raw: unknown, where: string): T {
  const result = schema.safeParse(raw);
  if (result.success) return result.data;
  const issues = result.error.issues.map((i) => `  ${i.path.join(".") || "(root)"}: ${i.message}` +
    (i.code === "unrecognized_keys" ? ` (${i.keys.join(", ")})` : ""));
  throw new KitError(`${where} is invalid:\n${issues.join("\n")}`);
}

export function parseModuleManifest(raw: unknown, where: string): ModuleManifest {
  return parseSchema(moduleSchema, raw, where) as ModuleManifest;
}

export function parseProfile(raw: unknown, where: string): Omit<Profile, "catalog"> {
  return parseSchema(profileSchema, raw, where);
}

export function parseCatalogIndex(raw: unknown, where: string): { name: string; modules: string[]; profiles: string[] } {
  return parseSchema(catalogIndexSchema, raw, where);
}

export function configValueProblem(key: string, field: ConfigField, value: unknown): string | null {
  const bad = (expected: string) => `config "${key}" must be ${expected}`;
  switch (field.type) {
    case "string": return typeof value === "string" ? null : bad("a string");
    case "number": return typeof value === "number" && Number.isFinite(value) ? null : bad("a number");
    case "boolean": return typeof value === "boolean" ? null : bad("a boolean");
    case "string[]":
      return Array.isArray(value) && value.every((v) => typeof v === "string") ? null : bad("a list of strings");
    case "enum":
      if (!field.values || field.values.length === 0) return `config "${key}" is an enum without values`;
      return typeof value === "string" && field.values.includes(value) ? null : bad(`one of ${field.values.join(", ")}`);
  }
}

/** Semantic checks that need the module's files. Returns problems; empty means valid. */
export function checkModule(def: ModuleDef): string[] {
  const problems: string[] = [];
  const files = Object.keys(def.files);
  const under = (prefix: string) => files.filter((f) => f.startsWith(prefix + "/"));

  for (const [path, content] of Object.entries(def.files)) {
    if (content.includes("\u0000")) problems.push(`${path}: binary files are not supported`);
  }
  for (const skill of def.contributes.skills) {
    if (!(`${skill}/SKILL.md` in def.files)) problems.push(`missing ${skill}/SKILL.md`);
  }
  const seenHooks = new Set<string>();
  for (const h of def.contributes.hooks) {
    if (!(h.run in def.files)) problems.push(`missing hook script ${h.run}`);
    const key = `${h.event} ${h.run}`;
    if (seenHooks.has(key)) problems.push(`duplicate hook ${key}`);
    seenHooks.add(key);
  }
  const allowed = new Set(knownPlaceholders(def));
  const checkPlaceholders = (path: string) => {
    for (const p of listPlaceholders(def.files[path] ?? "")) {
      if (!allowed.has(p)) problems.push(`${path}: unknown placeholder {{${p}}}`);
    }
  };
  for (const path of def.contributes.instructions) {
    if (!(path in def.files)) problems.push(`missing instructions file ${path}`);
    else checkPlaceholders(path);
  }
  for (const s of def.contributes.scaffold) {
    const sources = under(s.from);
    if (sources.length === 0) problems.push(`scaffold source ${s.from} has no files`);
    sources.forEach(checkPlaceholders);
  }
  if (def.contributes.scaffold.length > 0 && def.scopes.includes("user")) {
    problems.push("scaffold is project-scope only; remove \"user\" from scopes");
  }
  for (const [key, field] of Object.entries(def.config)) {
    if (field.type === "enum" && (!field.values || field.values.length === 0)) {
      problems.push(`config "${key}" is an enum without values`);
    } else if (field.default !== undefined) {
      const problem = configValueProblem(key, field, field.default);
      if (problem) problems.push(`${problem} (default)`);
    }
  }
  return problems;
}
