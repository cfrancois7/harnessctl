# Harness Kit Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `kit` CLI: a managed installer that puts catalog modules (skills, hooks, MCP config, instruction fragments, scaffolds) into Claude Code at project and user scope, with a lockfile that makes update, remove, and audit possible.

**Architecture:** Catalog modules are loaded into pure in-memory `ModuleDef`s (manifest + file contents). A harness adapter translates a module into a closed set of content-bearing `Operation`s. The executor *stages* all operations in memory (validating paths, parsing JSON, resolving conflicts), then *commits* them with backup and rollback. The lockfile records what each module owns; `remove` and `update` are derived from it.

**Tech Stack:** Node.js ≥ 20, TypeScript (ESM, `NodeNext`), vitest, zod 3, jsonc-parser, @clack/prompts. System `git` for catalogs. No other runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-harness-kit-core-design.md` — read it before starting any task.

## Global Constraints

- Node.js ≥ 20. ESM only (`"type": "module"`). Relative imports in `src/` and `test/` end in `.js` (NodeNext resolution), even though the files are `.ts`.
- Runtime dependencies are exactly: `zod@3`, `jsonc-parser`, `@clack/prompts`. Do not add others. Use `node:util` `parseArgs` for the CLI. Pin zod to major 3 (zod 4 changes `.default()` semantics this plan relies on).
- Nothing from a catalog is ever executed during install, update, or remove. Modules are data.
- Only `src/executor.ts` writes inside a scope root. Only `src/lockfile.ts` and `src/userconfig.ts` write kit state. Adapters and the planner are pure: no filesystem access.
- Every user-facing failure throws `KitError`; `main()` prints `error: <message>` and returns exit code 1. Never call `process.exit` outside `src/bin.ts`.
- All paths in operations and the lockfile are POSIX-style, relative to the scope root (project scope: repo root; user scope: the home directory).
- The home directory is always taken from `Env.home` (default `process.env.HARNESS_KIT_HOME ?? os.homedir()`), never from `os.homedir()` directly, so tests can redirect it.
- Module files are UTF-8 text. Binary files are a validation error in v1.
- Tested platforms: Linux, macOS, WSL. No shell-specific syntax; use `execFileSync("git", [...])`, never a shell string.
- Commit after every task with the message given in the task. Run `npm test` and `npm run typecheck` before each commit; both must pass.

## Deviations from the spec's wording (intentional, behaviour-preserving)

1. The spec lists `copyFile` and `renderTemplate` as separate operations. Because modules are loaded with their file contents and the adapter renders templates in memory, both collapse into one operation, `writeOwned`. The executor cannot tell them apart and does not need to.
2. The spec's adapter interface translates one contribution at a time and has `paths()` / `runtimeFiles()`. Here `translate()` takes the whole module, which lets the adapter emit the shared runtime shim and the module config file once. `allowedPrefixes()` replaces `paths()`. `detect()` is omitted until a second adapter exists; `--harness` defaults to `claude-code`.
3. "Byte-identical after remove" excludes the kit's own state directory `.harness-kit/` (lockfile, `.gitignore`, backups) as well as scaffolded files.
4. Known limitation, accepted: when the kit removes its last entry from a JSON container it prunes empty parents. A container the user already had *empty* before install (e.g. `"PreToolUse": []`) is pruned too. A text file that did not end with a newline gains one after a marked block is added and removed.

## File Structure

```
package.json · tsconfig.json · tsconfig.build.json · vitest.config.ts · .gitignore · README.md
assets/claude-code/runtime.mjs     hook runtime shim copied into targets (plain JS)
catalog/                           the public catalog (catalog.json, modules/kit-example, profiles/)
src/
  bin.ts                 process entry: calls main(), sets exit code
  cli.ts                 main(argv, env): flag parsing and command dispatch
  types.ts               all shared types and const enums
  env.ts                 Env, Flags, Command types shared by cli and commands
  errors.ts              KitError
  hash.ts                hashContent()
  template.ts            {{placeholder}} rendering
  diff.ts                lineDiff() for hook-script review on update
  schema.ts              zod schemas + semantic module checks
  paths.ts               kit state locations, project root discovery
  lockfile.ts            read/write lockfile
  userconfig.ts          read/write ~/.config/harness-kit/config.json
  executor.ts            resolveConfined(), stage(), commit()
  planner.ts             capabilities, config resolution, planModule(), planRemove()
  pipeline.ts            loadCatalogs(), openScope(), applyPlan(), installModules()
  prompts.ts             Prompter interface, clack implementation, promptConfig()
  status.ts              computeStatus()
  ops/json-merge.ts      format-preserving JSON entry upsert/remove
  ops/marked-block.ts    delimited block upsert/remove
  catalog/load.ts        loadCatalog(), resolveModule(), findProfile()
  catalog/source.ts      fetchCatalog() via git
  adapters/adapter.ts    HarnessAdapter interface, getAdapter()
  adapters/claude-code.ts
  commands/              init.ts add.ts remove.ts update.ts config.ts list.ts status.ts catalog.ts validate.ts
test/
  helpers.ts             temp dirs, git fixture catalogs, tree snapshots
  cli-helpers.ts         fake Prompter, runKit()
  fixtures/catalog/            "public" fixture catalog (modules alpha, beta; profile dev)
  fixtures/company-catalog/    "company" fixture catalog (module gamma; profile industrial)
  *.test.ts
```

---

### Task 1: Project tooling, shared types, template rendering

**Files:**
- Create: `package.json`, `tsconfig.json`, `tsconfig.build.json`, `vitest.config.ts`, `.gitignore`
- Create: `src/types.ts`, `src/errors.ts`, `src/hash.ts`, `src/template.ts`
- Test: `test/template.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: every type in `src/types.ts` (used by all later tasks); `KitError`; `hashContent(content: string): string` returning `"sha256:<hex>"`; `renderTemplate(text: string, vars: Record<string, string>, where: string): string`; `listPlaceholders(text: string): string[]`; `templateVars(manifest: { name: string; version: string }, config: Record<string, unknown>): Record<string, string>`; `knownPlaceholders(manifest: { config: Record<string, unknown> }): string[]`.

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "harness-kit",
  "version": "0.1.0",
  "description": "Managed starter kit for coding-agent harnesses",
  "type": "module",
  "bin": { "kit": "dist/bin.js" },
  "files": ["dist", "assets", "catalog"],
  "engines": { "node": ">=20" },
  "scripts": {
    "build": "tsc -p tsconfig.build.json",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "license": "MIT"
}
```

- [ ] **Step 2: Install dependencies**

Run:
```bash
npm install zod@3 jsonc-parser @clack/prompts
npm install -D typescript vitest @types/node@20
```
Expected: both succeed; `package.json` now has `dependencies` and `devDependencies`.

- [ ] **Step 3: Create the config files**

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["src", "test"]
}
```

`tsconfig.build.json`:
```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": { "noEmit": false, "outDir": "dist", "rootDir": "src", "declaration": false },
  "include": ["src"]
}
```

`vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["test/**/*.test.ts"], testTimeout: 30_000 },
});
```

`.gitignore`:
```
node_modules/
dist/
```

- [ ] **Step 4: Create `src/errors.ts` and `src/hash.ts`**

`src/errors.ts`:
```ts
/** A failure the user can act on. main() prints the message and exits 1. */
export class KitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "KitError";
  }
}
```

`src/hash.ts`:
```ts
import { createHash } from "node:crypto";

export function hashContent(content: string): string {
  return "sha256:" + createHash("sha256").update(content, "utf8").digest("hex");
}
```

- [ ] **Step 5: Create `src/types.ts`**

```ts
export const SCOPES = ["project", "user"] as const;
export type Scope = (typeof SCOPES)[number];

export const CAPABILITIES = [
  "skills", "instructions", "mcp",
  "pre-tool-hook", "post-tool-hook", "session-hook", "user-prompt-hook",
  "subagent-intercept", "usage-telemetry", "statusline",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const HOOK_EVENTS = [
  "pre-tool-use", "post-tool-use", "session-start", "user-prompt", "subagent-start", "stop",
] as const;
export type HookEvent = (typeof HOOK_EVENTS)[number];

export const TOOL_MATCHERS = ["*", "subagent", "shell", "edit"] as const;
export type ToolMatcher = (typeof TOOL_MATCHERS)[number];

export const CONFIG_TYPES = ["string", "number", "boolean", "enum", "string[]"] as const;
export type ConfigType = (typeof CONFIG_TYPES)[number];

export interface ConfigField {
  type: ConfigType;
  default?: unknown;
  prompt?: string;
  values?: string[];
}

export interface HookContribution {
  event: HookEvent;
  match?: { tool: ToolMatcher };
  /** Path inside the module, always under `hooks/`. */
  run: string;
  onError: "allow" | "deny";
}

export interface ScaffoldContribution { from: string; to: string }

/** module.json after validation and defaulting. */
export interface ModuleManifest {
  name: string;
  version: string;
  description: string;
  scopes: Scope[];
  requires: { capabilities: Capability[]; optional: Capability[]; env: string[] };
  config: Record<string, ConfigField>;
  contributes: {
    skills: string[];
    hooks: HookContribution[];
    instructions: string[];
    mcpServers: Record<string, unknown>;
    scaffold: ScaffoldContribution[];
  };
}

/** A manifest plus everything needed to install it without touching disk again. */
export interface ModuleDef extends ModuleManifest {
  /** Name of the catalog this module came from. */
  catalog: string;
  /** Every file in the module folder: POSIX relative path -> UTF-8 content. */
  files: Record<string, string>;
}

export interface ProfileEntry { scope?: Scope; config?: Record<string, unknown> }
export interface Profile {
  name: string;
  description: string;
  modules: Record<string, ProfileEntry>;
  catalog: string;
}

export interface ArrayMatch { commandContains: string }

export type Operation =
  | { kind: "writeOwned"; module: string; target: string; content: string; expectedHash?: string }
  | { kind: "scaffoldOnce"; module: string; target: string; content: string }
  | { kind: "mergeJson"; module: string; target: string; path: string[]; value: unknown; match?: ArrayMatch }
  | { kind: "markedBlock"; module: string; target: string; id: string; content: string }
  | { kind: "deleteOwned"; module: string; target: string; expectedHash: string }
  | { kind: "removeJson"; module: string; target: string; path: string[]; match?: ArrayMatch }
  | { kind: "removeBlock"; module: string; target: string; id: string };

export interface OwnedFile { path: string; hash: string }
export interface OwnedJson { file: string; pointer: string; match?: ArrayMatch }
export interface OwnedBlock { file: string; id: string }
export interface Owned { files: OwnedFile[]; json: OwnedJson[]; blocks: OwnedBlock[] }

export interface CatalogSource { url: string; ref?: string; subdir?: string }
export interface CatalogLock extends CatalogSource { sha: string }

export interface ModuleLock {
  catalog: string;
  version: string;
  config: Record<string, unknown>;
  owned: Owned;
  scaffolded: string[];
}

export interface Lockfile {
  lockVersion: 1;
  harness: string;
  profile?: string;
  catalogs: Record<string, CatalogLock>;
  /** Files the kit created through mergeJson/markedBlock; deleted again once blank. */
  createdFiles: string[];
  modules: Record<string, ModuleLock>;
}
```

- [ ] **Step 6: Write the failing test**

`test/template.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import { hashContent } from "../src/hash.js";
import { knownPlaceholders, listPlaceholders, renderTemplate, templateVars } from "../src/template.js";

describe("renderTemplate", () => {
  it("substitutes known placeholders, with or without inner spaces", () => {
    const out = renderTemplate("Hi {{config.greeting}} from {{ module.name }}", {
      "config.greeting": "hello", "module.name": "alpha",
    }, "alpha/instructions/a.md");
    expect(out).toBe("Hi hello from alpha");
  });

  it("throws KitError naming the file and placeholder when unknown", () => {
    expect(() => renderTemplate("{{config.nope}}", {}, "alpha/x.md"))
      .toThrowError(new KitError("alpha/x.md: unknown placeholder {{config.nope}}"));
  });

  it("leaves single-brace ${VAR} and { json } untouched", () => {
    expect(renderTemplate('{"a": "${TOKEN}"}', {}, "f")).toBe('{"a": "${TOKEN}"}');
  });
});

describe("template helpers", () => {
  it("lists unique placeholders", () => {
    expect(listPlaceholders("{{a.b}} {{a.b}} {{c}}")).toEqual(["a.b", "c"]);
  });

  it("builds vars from manifest and config; arrays join with ', '", () => {
    expect(templateVars({ name: "alpha", version: "1.0.0" }, { greeting: "hi", areas: ["api", "fw"], n: 3 }))
      .toEqual({ "module.name": "alpha", "module.version": "1.0.0",
                 "config.greeting": "hi", "config.areas": "api, fw", "config.n": "3" });
  });

  it("knows which placeholders a manifest allows", () => {
    expect(knownPlaceholders({ config: { greeting: {} } }))
      .toEqual(["module.name", "module.version", "config.greeting"]);
  });
});

describe("hashContent", () => {
  it("is a prefixed sha256 hex digest", () => {
    expect(hashContent("")).toBe("sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });
});
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `npx vitest run test/template.test.ts`
Expected: FAIL — cannot resolve `../src/template.js`.

- [ ] **Step 8: Implement `src/template.ts`**

```ts
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
```

- [ ] **Step 9: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: all tests PASS; typecheck prints nothing.

- [ ] **Step 10: Commit**

```bash
git add package.json package-lock.json tsconfig.json tsconfig.build.json vitest.config.ts .gitignore src test
git commit -m "chore: project tooling, shared types, template rendering"
```

---

### Task 2: Module schema, fixture catalogs, catalog loader

**Files:**
- Create: `src/schema.ts`, `src/catalog/load.ts`
- Create: fixture catalogs under `test/fixtures/catalog/` and `test/fixtures/company-catalog/` (listed in Step 1)
- Test: `test/schema.test.ts`, `test/catalog-load.test.ts`

**Interfaces:**
- Consumes: types from `src/types.ts`; `KitError`; `listPlaceholders`, `knownPlaceholders` from `src/template.ts`.
- Produces:
  - `parseModuleManifest(raw: unknown, where: string): ModuleManifest` (throws `KitError`)
  - `parseProfile(raw: unknown, where: string): Omit<Profile, "catalog">`
  - `parseCatalogIndex(raw: unknown, where: string): { name: string; modules: string[]; profiles: string[] }`
  - `checkModule(def: ModuleDef): string[]` — semantic problems, empty when valid
  - `interface Catalog { name: string; dir: string; modules: ModuleDef[]; profiles: Profile[]; invalid: { name: string; problems: string[] }[] }`
  - `loadCatalog(dir: string): Catalog`
  - `resolveModule(catalogs: Catalog[], ref: string): ModuleDef` — `ref` is `name` or `catalog:name`
  - `findProfile(catalogs: Catalog[], name: string): Profile`

- [ ] **Step 1: Create the fixture catalogs**

`test/fixtures/catalog/catalog.json`:
```json
{ "name": "public", "modules": ["modules/alpha", "modules/beta"], "profiles": ["profiles/dev.json"] }
```

`test/fixtures/catalog/modules/alpha/module.json`:
```json
{
  "name": "alpha",
  "version": "1.0.0",
  "description": "Fixture exercising every contribution type",
  "scopes": ["project"],
  "requires": { "capabilities": ["pre-tool-hook"], "env": ["ALPHA_TOKEN"] },
  "config": {
    "greeting": { "type": "string", "default": "hello", "prompt": "Greeting" },
    "areas": { "type": "string[]", "default": ["api"], "prompt": "Areas" }
  },
  "contributes": {
    "skills": ["skills/alpha-skill"],
    "hooks": [
      { "event": "pre-tool-use", "match": { "tool": "shell" }, "run": "hooks/check.mjs" },
      { "event": "session-start", "run": "hooks/start.mjs", "onError": "deny" }
    ],
    "instructions": ["instructions/alpha.md"],
    "mcpServers": { "alpha-mcp": { "command": "alpha-mcp", "env": { "TOKEN": "${ALPHA_TOKEN}" } } },
    "scaffold": [{ "from": "templates/docs", "to": "docs/context" }]
  }
}
```

`test/fixtures/catalog/modules/alpha/skills/alpha-skill/SKILL.md`:
```markdown
---
name: alpha-skill
description: Fixture skill. Use when testing the kit.
---

# Alpha skill

Say "alpha".
```

`test/fixtures/catalog/modules/alpha/hooks/check.mjs`:
```js
import { run } from "../../runtime.mjs";

run(({ tool, config, allow, deny }) => {
  const command = String(tool.input?.command ?? "");
  if (command.includes("alpha-deny-me")) return deny(`alpha (${config.greeting}) blocked this command`);
  return allow();
});
```

`test/fixtures/catalog/modules/alpha/hooks/start.mjs`:
```js
import { run } from "../../runtime.mjs";

run(({ config, warn }) => warn(`alpha active: ${config.greeting}`));
```

`test/fixtures/catalog/modules/alpha/instructions/alpha.md`:
```markdown
## Alpha

Greeting is "{{config.greeting}}". Areas: {{config.areas}}.
```

`test/fixtures/catalog/modules/alpha/templates/docs/INDEX.md`:
```markdown
# Context index ({{module.name}} {{module.version}})

Areas: {{config.areas}}
```

`test/fixtures/catalog/modules/beta/module.json`:
```json
{
  "name": "beta",
  "version": "0.2.0",
  "description": "Fixture with hooks only, both scopes",
  "scopes": ["user", "project"],
  "requires": { "capabilities": ["subagent-intercept"] },
  "config": {
    "mode": { "type": "enum", "values": ["warn", "block"], "default": "warn", "prompt": "Mode" }
  },
  "contributes": {
    "hooks": [{ "event": "pre-tool-use", "match": { "tool": "subagent" }, "run": "hooks/guard.mjs" }]
  }
}
```

`test/fixtures/catalog/modules/beta/hooks/guard.mjs`:
```js
import { run } from "../../runtime.mjs";

run(({ config, ask, deny }) =>
  config.mode === "block" ? deny("beta: sub-agents blocked") : ask("beta: confirm sub-agent"));
```

`test/fixtures/catalog/profiles/dev.json`:
```json
{
  "name": "dev",
  "description": "Fixture profile",
  "modules": {
    "alpha": { "scope": "project", "config": { "greeting": "hi dev" } },
    "beta": { "scope": "user" }
  }
}
```

`test/fixtures/company-catalog/catalog.json`:
```json
{ "name": "company", "modules": ["modules/gamma"], "profiles": ["profiles/industrial.json"] }
```

`test/fixtures/company-catalog/modules/gamma/module.json`:
```json
{
  "name": "gamma",
  "version": "0.1.0",
  "description": "Company fixture: instructions only",
  "scopes": ["project"],
  "contributes": { "instructions": ["instructions/gamma.md"] }
}
```

`test/fixtures/company-catalog/modules/gamma/instructions/gamma.md`:
```markdown
## Gamma

Company rules apply.
```

`test/fixtures/company-catalog/profiles/industrial.json`:
```json
{
  "name": "industrial",
  "description": "Company profile that bundles a public module",
  "modules": { "alpha": {}, "gamma": {} }
}
```

- [ ] **Step 2: Write the failing schema test**

`test/schema.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import { checkModule, parseModuleManifest, parseProfile } from "../src/schema.js";
import type { ModuleDef } from "../src/types.js";

const minimal = { name: "m", version: "1.0.0", scopes: ["project"] };

function def(manifest: object, files: Record<string, string>): ModuleDef {
  return { ...parseModuleManifest({ ...minimal, ...manifest }, "m"), catalog: "c", files };
}

describe("parseModuleManifest", () => {
  it("applies defaults", () => {
    const m = parseModuleManifest(minimal, "m");
    expect(m.description).toBe("");
    expect(m.requires).toEqual({ capabilities: [], optional: [], env: [] });
    expect(m.contributes).toEqual({ skills: [], hooks: [], instructions: [], mcpServers: {}, scaffold: [] });
  });

  it("defaults hook onError to allow", () => {
    const m = parseModuleManifest(
      { ...minimal, contributes: { hooks: [{ event: "stop", run: "hooks/a.mjs" }] } }, "m");
    expect(m.contributes.hooks[0]!.onError).toBe("allow");
  });

  it.each([
    [{ ...minimal, name: "Bad Name" }, "name"],
    [{ ...minimal, version: "1" }, "version"],
    [{ ...minimal, scopes: [] }, "scopes"],
    [{ ...minimal, extra: 1 }, "extra"],
    [{ ...minimal, requires: { capabilities: ["telepathy"] } }, "capabilities"],
    [{ ...minimal, contributes: { skills: ["../escape"] } }, "skills"],
    [{ ...minimal, contributes: { hooks: [{ event: "stop", run: "scripts/a.mjs" }] } }, "run"],
  ])("rejects invalid manifest %#", (raw, mention) => {
    expect(() => parseModuleManifest(raw, "modules/m")).toThrowError(KitError);
    expect(() => parseModuleManifest(raw, "modules/m")).toThrowError(new RegExp(`modules/m.*${mention}`, "s"));
  });
});

describe("checkModule", () => {
  it("accepts a consistent module", () => {
    const d = def(
      { config: { g: { type: "string", default: "x" } },
        contributes: { skills: ["skills/s"], hooks: [{ event: "stop", run: "hooks/a.mjs" }],
                       instructions: ["instructions/i.md"] } },
      { "skills/s/SKILL.md": "x", "hooks/a.mjs": "x", "instructions/i.md": "{{config.g}}" });
    expect(checkModule(d)).toEqual([]);
  });

  it("reports every inconsistency", () => {
    const d = def(
      { scopes: ["project", "user"],
        config: { mode: { type: "enum", default: "z" }, n: { type: "number", default: "five" } },
        contributes: {
          skills: ["skills/missing"],
          hooks: [{ event: "stop", run: "hooks/a.mjs" }, { event: "stop", run: "hooks/a.mjs" }],
          instructions: ["instructions/i.md"],
          scaffold: [{ from: "templates/none", to: "docs" }] } },
      { "instructions/i.md": "{{config.unknown}}", "bin/blob": "a\u0000b" });
    const problems = checkModule(d).join("\n");
    expect(problems).toContain("skills/missing/SKILL.md");
    expect(problems).toContain("hooks/a.mjs");
    expect(problems).toContain("duplicate hook");
    expect(problems).toContain("{{config.unknown}}");
    expect(problems).toContain("templates/none");
    expect(problems).toContain("scaffold is project-scope only");
    expect(problems).toContain('config "mode"');
    expect(problems).toContain('config "n"');
    expect(problems).toContain("bin/blob");
  });
});

describe("parseProfile", () => {
  it("parses entries with optional scope and config", () => {
    const p = parseProfile({ name: "dev", modules: { a: { scope: "user" }, b: {} } }, "p");
    expect(p).toEqual({ name: "dev", description: "", modules: { a: { scope: "user" }, b: {} } });
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npx vitest run test/schema.test.ts`
Expected: FAIL — cannot resolve `../src/schema.js`.

- [ ] **Step 4: Implement `src/schema.ts`**

```ts
import { z } from "zod";
import { KitError } from "./errors.js";
import { knownPlaceholders, listPlaceholders } from "./template.js";
import {
  CAPABILITIES, CONFIG_TYPES, HOOK_EVENTS, SCOPES, TOOL_MATCHERS,
  type ConfigField, type ModuleDef, type ModuleManifest, type Profile,
} from "./types.js";

const relPath = z.string().min(1).refine(
  (p) => !p.startsWith("/") && !p.includes("\\") && !p.split("/").includes("..") && !p.split("/").includes(""),
  "must be a relative POSIX path without '..'",
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

function parse<T>(schema: z.ZodType<T, z.ZodTypeDef, unknown>, raw: unknown, where: string): T {
  const result = schema.safeParse(raw);
  if (result.success) return result.data;
  const issues = result.error.issues.map((i) => `  ${i.path.join(".") || "(root)"}: ${i.message}` +
    (i.code === "unrecognized_keys" ? ` (${i.keys.join(", ")})` : ""));
  throw new KitError(`${where} is invalid:\n${issues.join("\n")}`);
}

export function parseModuleManifest(raw: unknown, where: string): ModuleManifest {
  return parse(moduleSchema, raw, where) as ModuleManifest;
}

export function parseProfile(raw: unknown, where: string): Omit<Profile, "catalog"> {
  return parse(profileSchema, raw, where);
}

export function parseCatalogIndex(raw: unknown, where: string): { name: string; modules: string[]; profiles: string[] } {
  return parse(catalogIndexSchema, raw, where);
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
```

- [ ] **Step 5: Run the schema test to verify it passes**

Run: `npx vitest run test/schema.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the failing loader test**

`test/catalog-load.test.ts`:
```ts
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findProfile, loadCatalog, resolveModule } from "../src/catalog/load.js";
import { KitError } from "../src/errors.js";

const PUBLIC = join(import.meta.dirname, "fixtures/catalog");
const COMPANY = join(import.meta.dirname, "fixtures/company-catalog");

describe("loadCatalog", () => {
  it("loads modules with their files and profiles", () => {
    const cat = loadCatalog(PUBLIC);
    expect(cat.name).toBe("public");
    expect(cat.invalid).toEqual([]);
    expect(cat.modules.map((m) => m.name)).toEqual(["alpha", "beta"]);
    const alpha = cat.modules[0]!;
    expect(alpha.catalog).toBe("public");
    expect(Object.keys(alpha.files).sort()).toEqual([
      "hooks/check.mjs", "hooks/start.mjs", "instructions/alpha.md", "module.json",
      "skills/alpha-skill/SKILL.md", "templates/docs/INDEX.md",
    ]);
    expect(cat.profiles[0]).toMatchObject({ name: "dev", catalog: "public" });
  });

  it("records invalid modules instead of throwing", () => {
    const dir = mkdtempSync(join(tmpdir(), "kit-cat-"));
    cpSync(PUBLIC, dir, { recursive: true });
    const manifest = join(dir, "modules/beta/module.json");
    const raw = JSON.parse(readFileSync(manifest, "utf8"));
    raw.contributes.hooks[0].run = "hooks/nope.mjs";
    writeFileSync(manifest, JSON.stringify(raw));
    const cat = loadCatalog(dir);
    expect(cat.modules.map((m) => m.name)).toEqual(["alpha"]);
    expect(cat.invalid).toEqual([{ name: "beta", problems: ["missing hook script hooks/nope.mjs"] }]);
  });

  it("throws when catalog.json is missing", () => {
    expect(() => loadCatalog(tmpdir())).toThrowError(KitError);
  });
});

describe("name resolution", () => {
  const catalogs = [loadCatalog(PUBLIC), loadCatalog(COMPANY)];

  it("resolves unqualified and qualified names across catalogs", () => {
    expect(resolveModule(catalogs, "gamma").catalog).toBe("company");
    expect(resolveModule(catalogs, "public:alpha").name).toBe("alpha");
  });

  it("explains unknown, ambiguous and invalid modules", () => {
    expect(() => resolveModule(catalogs, "nope")).toThrowError(/module "nope" not found/);
    const other = { ...catalogs[0]!, name: "other",
      modules: catalogs[0]!.modules.map((m) => ({ ...m, catalog: "other" })) };
    expect(() => resolveModule([catalogs[0]!, other], "alpha"))
      .toThrowError(/ambiguous.*public:alpha.*other:alpha/s);
    const broken = { ...catalogs[1]!, modules: [], invalid: [{ name: "gamma", problems: ["boom"] }] };
    expect(() => resolveModule([broken], "gamma")).toThrowError(/gamma.*invalid.*boom/s);
  });

  it("finds profiles in any catalog", () => {
    expect(findProfile(catalogs, "industrial").modules).toHaveProperty("alpha");
    expect(() => findProfile(catalogs, "nope")).toThrowError(/profile "nope" not found.*dev, industrial/s);
  });
});
```

- [ ] **Step 7: Run it to verify it fails**

Run: `npx vitest run test/catalog-load.test.ts`
Expected: FAIL — cannot resolve `../src/catalog/load.js`.

- [ ] **Step 8: Implement `src/catalog/load.ts`**

```ts
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
```

- [ ] **Step 9: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 10: Commit**

```bash
git add src/schema.ts src/catalog test/schema.test.ts test/catalog-load.test.ts test/fixtures
git commit -m "feat: module schema, semantic checks, catalog loader"
```

---
### Task 3: Format-preserving JSON entry merge

This primitive edits `settings.json`, `.mcp.json`, and `~/.claude.json` without disturbing anything the kit does not own. The approach below was prototyped against jsonc-parser and round-trips byte-for-byte: **insert** with a raw `modify()` edit and then `format()` only the inserted range (formatting the whole edit, jsonc-parser's default, reformats the neighbouring sibling); **remove** by slicing node offsets from the parse tree (jsonc-parser's own removal leaves stray whitespace or reformats siblings).

**Files:**
- Create: `src/ops/json-merge.ts`
- Test: `test/json-merge.test.ts`

**Interfaces:**
- Consumes: `KitError`; `ArrayMatch` from `src/types.ts`.
- Produces:
  - `upsertJsonEntry(text: string, file: string, path: string[], value: unknown, match?: ArrayMatch): string` — without `match`, sets the object property at `path`. With `match`, `path` points at an array; the entry whose JSON contains `match.commandContains` is replaced, or `value` is appended. Empty/whitespace `text` is treated as `{}`. Returns `text` unchanged when already up to date.
  - `removeJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): string` — removes the entry and prunes parents left empty.
  - `hasJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): boolean`
  - `isEmptyJson(text: string): boolean` — parses to `{}` and contains no comments.
  - `toPointer(path: string[]): string`, `fromPointer(pointer: string): string[]` — RFC 6901.
  - All throw `KitError("cannot parse <file>: …")` when `text` is not a JSON object (JSONC comments and trailing commas are accepted).

- [ ] **Step 1: Write the failing test**

`test/json-merge.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import {
  fromPointer, hasJsonEntry, isEmptyJson, removeJsonEntry, toPointer, upsertJsonEntry,
} from "../src/ops/json-merge.js";

const hookEntry = (module: string, script: string, matcher?: string) => ({
  ...(matcher ? { matcher } : {}),
  hooks: [{ type: "command", command: `node x/kit/hooks/${module}/${script}` }],
});
const M1 = { commandContains: "kit/hooks/m/check.mjs" };
const M2 = { commandContains: "kit/hooks/m/start.mjs" };
const M3 = { commandContains: "kit/hooks/n/check.mjs" };

const CASES: Record<string, string> = {
  canonical2: `{\n  "permissions": {\n    "allow": ["Bash(npm test)"]\n  },\n  "model": "sonnet"\n}\n`,
  compactSiblingsAndComment: `{\n    "permissions": { "allow": [] },\n    // a comment\n    "hooks": {\n        "PreToolUse": [\n            { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo hi" }] }\n        ]\n    }\n}\n`,
  compactLastProperty: `{\n  "model": "sonnet",\n  "permissions": { "allow": [] }\n}\n`,
  oneLine: `{"model":"sonnet"}`,
  tabs: `{\n\t"a": 1\n}\n`,
  crlf: `{\r\n  "a": 1\r\n}\r\n`,
  emptyObject: `{}\n`,
};

function installAll(text: string): string {
  let t = upsertJsonEntry(text, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Agent"), M1);
  t = upsertJsonEntry(t, "f", ["hooks", "PreToolUse"], hookEntry("n", "check.mjs", "Bash"), M3);
  t = upsertJsonEntry(t, "f", ["hooks", "SessionStart"], hookEntry("m", "start.mjs"), M2);
  return upsertJsonEntry(t, "f", ["mcpServers", "plm"], { command: "plm-mcp" });
}

describe.each(Object.entries(CASES))("json merge on %s", (_name, original) => {
  it("adds entries and keeps the result valid", () => {
    const parsed = JSON.parse(installAll(original).replace(/^\s*\/\/.*$/gm, ""));
    expect(parsed.hooks.PreToolUse.at(-2).matcher).toBe("Agent");
    expect(parsed.hooks.PreToolUse.at(-1).matcher).toBe("Bash");
    expect(parsed.hooks.SessionStart).toHaveLength(1);
    expect(parsed.mcpServers.plm).toEqual({ command: "plm-mcp" });
  });

  it("does not touch text it does not own", () => {
    const installed = installAll(original);
    // Compare each original line minus its outermost bracket/comma, which an insertion may legitimately follow.
    const core = (line: string) => line.trim().replace(/^[{[]\s*/, "").replace(/\s*[}\]]?,?$/, "");
    for (const line of original.split(/\r?\n/).map(core).filter((l) => l !== "")) {
      expect(installed).toContain(line);
    }
  });

  it("is idempotent", () => {
    const once = installAll(original);
    expect(installAll(once)).toBe(once);
  });

  it("round-trips byte-for-byte when entries are removed in a different order", () => {
    let t = installAll(original);
    t = removeJsonEntry(t, "f", ["hooks", "PreToolUse"], M1);
    t = removeJsonEntry(t, "f", ["mcpServers", "plm"]);
    t = removeJsonEntry(t, "f", ["hooks", "SessionStart"], M2);
    t = removeJsonEntry(t, "f", ["hooks", "PreToolUse"], M3);
    expect(t).toBe(original);
  });
});

describe("json merge details", () => {
  it("treats empty text as an empty object", () => {
    const t = upsertJsonEntry("", "f", ["mcpServers", "a"], { command: "a" });
    expect(JSON.parse(t)).toEqual({ mcpServers: { a: { command: "a" } } });
    expect(isEmptyJson(removeJsonEntry(t, "f", ["mcpServers", "a"]))).toBe(true);
  });

  it("replaces a matched array entry instead of appending", () => {
    let t = upsertJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Agent"), M1);
    t = upsertJsonEntry(t, "f", ["hooks", "PreToolUse"], hookEntry("m", "check.mjs", "Bash"), M1);
    const arr = JSON.parse(t).hooks.PreToolUse;
    expect(arr).toHaveLength(1);
    expect(arr[0].matcher).toBe("Bash");
  });

  it("reports presence", () => {
    const t = installAll(CASES.canonical2!);
    expect(hasJsonEntry(t, "f", ["hooks", "PreToolUse"], M1)).toBe(true);
    expect(hasJsonEntry(t, "f", ["mcpServers", "plm"])).toBe(true);
    expect(hasJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], M1)).toBe(false);
    expect(hasJsonEntry(CASES.canonical2!, "f", ["mcpServers", "plm"])).toBe(false);
  });

  it("removal of something absent is a no-op", () => {
    expect(removeJsonEntry(CASES.canonical2!, "f", ["hooks", "PreToolUse"], M1)).toBe(CASES.canonical2);
    expect(removeJsonEntry(CASES.canonical2!, "f", ["mcpServers", "zzz"])).toBe(CASES.canonical2);
  });

  it("refuses files it cannot parse, and non-object roots", () => {
    expect(() => upsertJsonEntry("{ nope", "settings.json", ["a"], 1))
      .toThrowError(new KitError("cannot parse settings.json: not a valid JSON object"));
    expect(() => upsertJsonEntry("[1]", "settings.json", ["a"], 1)).toThrowError(KitError);
    expect(() => upsertJsonEntry('{"hooks":{"PreToolUse":{}}}', "s.json", ["hooks", "PreToolUse"], {}, M1))
      .toThrowError(/s\.json: \/hooks\/PreToolUse is not an array/);
  });

  it("isEmptyJson is false when comments remain", () => {
    expect(isEmptyJson("{}\n")).toBe(true);
    expect(isEmptyJson("{\n  // keep me\n}\n")).toBe(false);
    expect(isEmptyJson('{"a":1}')).toBe(false);
    expect(isEmptyJson("not json")).toBe(false);
  });

  it("converts JSON pointers", () => {
    expect(toPointer(["mcpServers", "a/b~c"])).toBe("/mcpServers/a~1b~0c");
    expect(fromPointer("/mcpServers/a~1b~0c")).toEqual(["mcpServers", "a/b~c"]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/json-merge.test.ts`
Expected: FAIL — cannot resolve `../src/ops/json-merge.js`.

- [ ] **Step 3: Implement `src/ops/json-merge.ts`**

```ts
import {
  applyEdits, findNodeAtLocation, format, modify, parse, parseTree,
  type FormattingOptions, type ModificationOptions, type ParseError,
} from "jsonc-parser";
import { KitError } from "../errors.js";
import type { ArrayMatch } from "../types.js";

type Path = (string | number)[];

function detectFormat(text: string): FormattingOptions {
  const indent = text.match(/\n([ \t]+)\S/)?.[1] ?? "  ";
  const tabs = indent.includes("\t");
  return { insertSpaces: !tabs, tabSize: tabs ? 1 : indent.length, eol: text.includes("\r\n") ? "\r\n" : "\n" };
}

function parseObject(text: string, file: string): Record<string, unknown> {
  const errors: ParseError[] = [];
  const value: unknown = parse(text, errors, { allowTrailingComma: true });
  if (errors.length > 0 || value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new KitError(`cannot parse ${file}: not a valid JSON object`);
  }
  return value as Record<string, unknown>;
}

function getAt(root: unknown, path: Path): unknown {
  let current = root;
  for (const segment of path) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string | number, unknown>)[segment];
  }
  return current;
}

const isEmptyContainer = (v: unknown): boolean =>
  v !== null && typeof v === "object" && Object.keys(v as object).length === 0;

const entryMatches = (entry: unknown, match: ArrayMatch): boolean =>
  JSON.stringify(entry).includes(match.commandContains);

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

/** Set a value. Only the inserted range is formatted, so neighbouring text keeps its bytes. */
function setAt(src: string, file: string, path: Path, value: unknown, options: ModificationOptions = {}): string {
  const formattingOptions = detectFormat(src);
  if (isEmptyContainer(parseObject(src, file))) {
    return applyEdits(src, modify(src, path, value, { ...options, formattingOptions }));
  }
  const edits = modify(src, path, value, options);
  if (edits.length === 0) return src;
  const raw = applyEdits(src, edits);
  const inserted = { offset: edits[0]!.offset, length: edits[0]!.content.length };
  return applyEdits(raw, format(raw, inserted, formattingOptions));
}

/** Remove a node by offsets: exactly the text an insertion added, including its separator. */
function deleteAt(src: string, path: Path): string {
  const tree = parseTree(src);
  const valueNode = tree ? findNodeAtLocation(tree, path) : undefined;
  if (!valueNode?.parent) return src;
  const node = valueNode.parent.type === "property" ? valueNode.parent : valueNode;
  const container = node.parent;
  const siblings = container?.children;
  if (!container || !siblings) return src;
  const index = siblings.indexOf(node);
  let start: number;
  let end: number;
  if (index > 0) {
    const previous = siblings[index - 1]!;
    start = previous.offset + previous.length;
    end = node.offset + node.length;
  } else if (siblings.length > 1) {
    start = node.offset;
    end = siblings[1]!.offset;
  } else {
    start = container.offset + 1;
    end = container.offset + container.length - 1;
  }
  return src.slice(0, start) + src.slice(end);
}

function arrayAt(root: unknown, file: string, path: string[]): unknown[] | undefined {
  const value = getAt(root, path);
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new KitError(`${file}: ${toPointer(path)} is not an array`);
  return value;
}

export function upsertJsonEntry(text: string, file: string, path: string[], value: unknown, match?: ArrayMatch): string {
  const src = text.trim() === "" ? "{}" : text;
  const root = parseObject(src, file);
  if (!match) return same(getAt(root, path), value) ? src : setAt(src, file, path, value);
  const array = arrayAt(root, file, path);
  if (array === undefined) return setAt(src, file, path, [value]);
  const index = array.findIndex((entry) => entryMatches(entry, match));
  if (index >= 0) return same(array[index], value) ? src : setAt(src, file, [...path, index], value);
  return setAt(src, file, [...path, array.length], value, { isArrayInsertion: true });
}

export function removeJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): string {
  if (text.trim() === "") return text;
  const root = parseObject(text, file);
  let target: Path = path;
  if (match) {
    const index = (arrayAt(root, file, path) ?? []).findIndex((entry) => entryMatches(entry, match));
    if (index < 0) return text;
    target = [...path, index];
  } else if (getAt(root, path) === undefined) {
    return text;
  }
  let src = deleteAt(text, target);
  let parent = target.slice(0, -1);
  while (parent.length > 0 && isEmptyContainer(getAt(parseObject(src, file), parent))) {
    src = deleteAt(src, parent);
    parent = parent.slice(0, -1);
  }
  return src;
}

export function hasJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): boolean {
  if (text.trim() === "") return false;
  const root = parseObject(text, file);
  if (!match) return getAt(root, path) !== undefined;
  return (arrayAt(root, file, path) ?? []).some((entry) => entryMatches(entry, match));
}

export function isEmptyJson(text: string): boolean {
  if (/\/\/|\/\*/.test(text)) return false;
  try {
    return isEmptyContainer(parseObject(text.trim() === "" ? "{}" : text, ""));
  } catch {
    return false;
  }
}

export function toPointer(path: string[]): string {
  return path.map((s) => "/" + s.replace(/~/g, "~0").replace(/\//g, "~1")).join("");
}

export function fromPointer(pointer: string): string[] {
  return pointer.split("/").slice(1).map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `npx vitest run test/json-merge.test.ts && npm run typecheck`
Expected: PASS. If a round-trip case fails, print `JSON.stringify` of both strings to see the differing bytes; do not loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/ops/json-merge.ts test/json-merge.test.ts
git commit -m "feat: format-preserving JSON entry merge"
```

---

### Task 4: Marked blocks

**Files:**
- Create: `src/ops/marked-block.ts`
- Test: `test/marked-block.test.ts`

**Interfaces:**
- Consumes: `KitError`.
- Produces: `upsertBlock(text: string, id: string, content: string): string`; `removeBlock(text: string, id: string): string`; `hasBlock(text: string, id: string): boolean`. Delimiters are exactly `<!-- kit:<id>:start -->` and `<!-- kit:<id>:end -->`.

- [ ] **Step 1: Write the failing test**

`test/marked-block.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { hasBlock, removeBlock, upsertBlock } from "../src/ops/marked-block.js";

const BLOCK = "<!-- kit:alpha:start -->\nhello\n<!-- kit:alpha:end -->\n";

describe("marked blocks", () => {
  it("creates the block in an empty file", () => {
    expect(upsertBlock("", "alpha", "hello\n")).toBe(BLOCK);
  });

  it("appends after a blank line and round-trips", () => {
    const original = "# Project\n\nRules.\n";
    const withBlock = upsertBlock(original, "alpha", "hello");
    expect(withBlock).toBe(original + "\n" + BLOCK);
    expect(removeBlock(withBlock, "alpha")).toBe(original);
  });

  it("round-trips a file that already ends with a blank line", () => {
    const original = "# Project\n\n";
    expect(removeBlock(upsertBlock(original, "alpha", "hello"), "alpha")).toBe(original);
  });

  it("replaces content in place, leaving surrounding text and other blocks alone", () => {
    const text = "top\n\n" + BLOCK + "\n<!-- kit:beta:start -->\nb\n<!-- kit:beta:end -->\nbottom\n";
    const updated = upsertBlock(text, "alpha", "changed");
    expect(updated).toBe(text.replace("hello", "changed"));
    expect(upsertBlock(updated, "alpha", "changed")).toBe(updated);
  });

  it("removes only its own block", () => {
    const text = upsertBlock(upsertBlock("top\n", "alpha", "a"), "beta", "b");
    const removed = removeBlock(text, "alpha");
    expect(hasBlock(removed, "alpha")).toBe(false);
    expect(hasBlock(removed, "beta")).toBe(true);
    expect(removeBlock(removed, "beta")).toBe("top\n");
  });

  it("is a no-op when the block is absent", () => {
    expect(removeBlock("text\n", "alpha")).toBe("text\n");
  });

  it("refuses an unterminated block", () => {
    expect(() => upsertBlock("<!-- kit:alpha:start -->\noops\n", "alpha", "x"))
      .toThrowError(/kit:alpha.*no end marker/);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/marked-block.test.ts`
Expected: FAIL — cannot resolve `../src/ops/marked-block.js`.

- [ ] **Step 3: Implement `src/ops/marked-block.ts`**

```ts
import { KitError } from "../errors.js";

const startMarker = (id: string) => `<!-- kit:${id}:start -->`;
const endMarker = (id: string) => `<!-- kit:${id}:end -->`;

function findBlock(text: string, id: string): { start: number; end: number } | null {
  const start = text.indexOf(startMarker(id));
  if (start < 0) return null;
  const endAt = text.indexOf(endMarker(id), start);
  if (endAt < 0) throw new KitError(`block kit:${id} has a start marker but no end marker`);
  let end = endAt + endMarker(id).length;
  if (text[end] === "\n") end += 1;
  return { start, end };
}

export function hasBlock(text: string, id: string): boolean {
  return findBlock(text, id) !== null;
}

export function upsertBlock(text: string, id: string, content: string): string {
  const block = `${startMarker(id)}\n${content.trim()}\n${endMarker(id)}\n`;
  const range = findBlock(text, id);
  if (range) return text.slice(0, range.start) + block + text.slice(range.end);
  if (text === "") return block;
  return text + (text.endsWith("\n") ? "\n" : "\n\n") + block;
}

export function removeBlock(text: string, id: string): string {
  const range = findBlock(text, id);
  if (!range) return text;
  let start = range.start;
  // upsertBlock separated the block with one blank line; take that separator back out.
  if (text.slice(0, start).endsWith("\n\n")) start -= 1;
  return text.slice(0, start) + text.slice(range.end);
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `npx vitest run test/marked-block.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ops/marked-block.ts test/marked-block.test.ts
git commit -m "feat: marked block upsert and removal"
```

---

### Task 5: Executor — path confinement, staging, commit with rollback

The executor works in two phases. `stage()` reads current files, applies every operation **in memory**, resolves conflicts, and throws before anything is written if any operation is invalid. `commit()` writes the staged result, backing up originals and restoring them if a write fails.

**Files:**
- Create: `src/executor.ts`
- Test: `test/executor.test.ts`

**Interfaces:**
- Consumes: `Operation`, `Owned` from `src/types.ts`; `hashContent`; `upsertJsonEntry`, `removeJsonEntry`, `isEmptyJson`, `toPointer`; `upsertBlock`, `removeBlock`; `KitError`.
- Produces:
  - `interface ScopeRoot { root: string; allowed: string[] }` — `allowed` entries are relative prefixes: `""` allows everything, `"dir/"` allows a subtree, anything else allows that exact file.
  - `resolveConfined(scopeRoot: ScopeRoot, target: string): string` — absolute path, or throws `KitError`. Always rejects targets under `.git/` (a module could otherwise plant a git hook, which is code execution) and under `.harness-kit/` (the kit's own state).
  - `interface Conflict { target: string; reason: "modified" | "unowned"; current: string; incoming: string | null }`
  - `interface StageOptions { scopeRoot: ScopeRoot; createdFiles: string[]; onConflict: (c: Conflict) => Promise<"keep" | "overwrite"> }`
  - `interface StagedWrite { target: string; before: string | null; after: string | null }` (`null` = file absent)
  - `interface ModuleRecord { owned: Owned; scaffolded: string[] }`
  - `interface Staged { writes: StagedWrite[]; records: Record<string, ModuleRecord>; createdFiles: string[]; warnings: string[] }` — `createdFiles` is the new value for `Lockfile.createdFiles`.
  - `stage(ops: Operation[], options: StageOptions): Promise<Staged>`
  - `commit(staged: Staged, scopeRoot: ScopeRoot, backupDir: string, onWrite?: (target: string) => void): void` — `onWrite` is a test seam called before each write.

- [ ] **Step 1: Write the failing test**

`test/executor.test.ts`:
```ts
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import { commit, resolveConfined, stage, type Conflict, type ScopeRoot } from "../src/executor.js";
import { hashContent } from "../src/hash.js";
import type { Operation } from "../src/types.js";

let root: string;
let scopeRoot: ScopeRoot;
let backupDir: string;
const read = (rel: string) => readFileSync(join(root, rel), "utf8");
const write = (rel: string, content: string) => {
  mkdirSync(join(root, rel, ".."), { recursive: true });
  writeFileSync(join(root, rel), content);
};
const keep = async () => "keep" as const;
const overwrite = async () => "overwrite" as const;
const opts = (onConflict = keep, createdFiles: string[] = []) => ({ scopeRoot, createdFiles, onConflict });

beforeEach(() => {
  root = realpathSync(mkdtempSync(join(tmpdir(), "kit-exec-"))); // macOS: /tmp is a symlink
  scopeRoot = { root, allowed: [""] };
  backupDir = join(root, ".harness-kit/backup/t1");
});

describe("resolveConfined", () => {
  it.each(["../x", "/etc/passwd", "a/../../x", "a\\b", "", "a//b"])("rejects %j", (target) => {
    expect(() => resolveConfined(scopeRoot, target)).toThrowError(KitError);
  });

  it("never lets a module write into .git or the kit's own state directory", () => {
    expect(() => resolveConfined(scopeRoot, ".git/hooks/pre-commit")).toThrowError(/protected directory/);
    expect(() => resolveConfined(scopeRoot, ".harness-kit/lock.json")).toThrowError(/protected directory/);
    expect(resolveConfined(scopeRoot, ".github/workflows/ci.yml")).toBe(join(root, ".github/workflows/ci.yml"));
  });

  it("rejects a symlinked directory that escapes the root", () => {
    const outside = mkdtempSync(join(tmpdir(), "kit-outside-"));
    symlinkSync(outside, join(root, "link"));
    expect(() => resolveConfined(scopeRoot, "link/file.txt")).toThrowError(/symlink/);
  });

  it("enforces allowed prefixes", () => {
    const user: ScopeRoot = { root, allowed: [".claude/", ".claude.json"] };
    expect(resolveConfined(user, ".claude/skills/a/SKILL.md")).toBe(join(root, ".claude/skills/a/SKILL.md"));
    expect(resolveConfined(user, ".claude.json")).toBe(join(root, ".claude.json"));
    expect(() => resolveConfined(user, ".ssh/config")).toThrowError(/outside allowed/);
    expect(() => resolveConfined(user, ".claude.json.bak")).toThrowError(/outside allowed/);
  });
});

describe("stage + commit", () => {
  it("writes new owned files and records their hashes", async () => {
    const ops: Operation[] = [{ kind: "writeOwned", module: "m", target: ".claude/skills/s/SKILL.md", content: "skill" }];
    const staged = await stage(ops, opts());
    expect(existsSync(join(root, ".claude"))).toBe(false); // staging writes nothing
    commit(staged, scopeRoot, backupDir);
    expect(read(".claude/skills/s/SKILL.md")).toBe("skill");
    expect(staged.records.m!.owned.files).toEqual([{ path: ".claude/skills/s/SKILL.md", hash: hashContent("skill") }]);
    expect(existsSync(backupDir)).toBe(false); // nothing pre-existing, nothing to back up
  });

  it("records ownership without writing when content is already identical", async () => {
    write("a.txt", "same");
    const staged = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "same" }], opts());
    expect(staged.writes).toEqual([]);
    expect(staged.records.m!.owned.files).toHaveLength(1);
  });

  it("overwrites an owned, unmodified file without asking", async () => {
    write("a.txt", "v1");
    let asked = false;
    const staged = await stage(
      [{ kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") }],
      opts(async () => { asked = true; return "keep"; }));
    commit(staged, scopeRoot, backupDir);
    expect(asked).toBe(false);
    expect(read("a.txt")).toBe("v2");
    expect(readFileSync(join(backupDir, "a.txt"), "utf8")).toBe("v1");
  });

  it("asks about a user-modified owned file; keep leaves it and warns", async () => {
    write("a.txt", "user edit");
    const seen: Conflict[] = [];
    const staged = await stage(
      [{ kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") }],
      opts(async (c) => { seen.push(c); return "keep"; }));
    expect(seen).toEqual([{ target: "a.txt", reason: "modified", current: "user edit", incoming: "v2" }]);
    expect(staged.writes).toEqual([]);
    expect(staged.warnings).toEqual(["kept your version of a.txt"]);
    expect(staged.records.m!.owned.files).toEqual([{ path: "a.txt", hash: hashContent("v2") }]);
  });

  it("does not take ownership of a pre-existing unowned file that the user keeps", async () => {
    write("a.txt", "theirs");
    const staged = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "ours" }], opts());
    expect(staged.records.m!.owned.files).toEqual([]);
    const forced = await stage([{ kind: "writeOwned", module: "m", target: "a.txt", content: "ours" }], opts(overwrite));
    expect(forced.writes).toEqual([{ target: "a.txt", before: "theirs", after: "ours" }]);
  });

  it("scaffoldOnce creates but never overwrites", async () => {
    write("docs/INDEX.md", "mine");
    const staged = await stage([
      { kind: "scaffoldOnce", module: "m", target: "docs/INDEX.md", content: "template" },
      { kind: "scaffoldOnce", module: "m", target: "docs/roadmap.md", content: "roadmap" },
    ], opts());
    commit(staged, scopeRoot, backupDir);
    expect(read("docs/INDEX.md")).toBe("mine");
    expect(read("docs/roadmap.md")).toBe("roadmap");
    expect(staged.records.m!.scaffolded).toEqual(["docs/roadmap.md"]);
  });

  it("chains several merges into one file and tracks created files", async () => {
    const ops: Operation[] = [
      { kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: { command: "a" } },
      { kind: "mergeJson", module: "n", target: ".mcp.json", path: ["mcpServers", "b"], value: { command: "b" } },
      { kind: "markedBlock", module: "m", target: "CLAUDE.md", id: "m", content: "rules" },
    ];
    const staged = await stage(ops, opts());
    commit(staged, scopeRoot, backupDir);
    expect(Object.keys(JSON.parse(read(".mcp.json")).mcpServers)).toEqual(["a", "b"]);
    expect(staged.createdFiles).toEqual([".mcp.json", "CLAUDE.md"]);
    expect(staged.records.m!.owned.json).toEqual([{ file: ".mcp.json", pointer: "/mcpServers/a" }]);
    expect(staged.records.m!.owned.blocks).toEqual([{ file: "CLAUDE.md", id: "m" }]);
  });

  it("deletes files it created once removals leave them blank, and prunes empty directories", async () => {
    const install: Operation[] = [
      { kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: { command: "a" } },
      { kind: "markedBlock", module: "m", target: "CLAUDE.md", id: "m", content: "rules" },
      { kind: "writeOwned", module: "m", target: ".claude/kit/hooks/m/x.mjs", content: "x" },
    ];
    const first = await stage(install, opts());
    commit(first, scopeRoot, backupDir);
    const removal: Operation[] = [
      { kind: "removeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"] },
      { kind: "removeBlock", module: "m", target: "CLAUDE.md", id: "m" },
      { kind: "deleteOwned", module: "m", target: ".claude/kit/hooks/m/x.mjs", expectedHash: hashContent("x") },
    ];
    const second = await stage(removal, opts(keep, first.createdFiles));
    commit(second, scopeRoot, join(root, ".harness-kit/backup/t2"));
    expect(existsSync(join(root, ".mcp.json"))).toBe(false);
    expect(existsSync(join(root, "CLAUDE.md"))).toBe(false);
    expect(existsSync(join(root, ".claude"))).toBe(false);
    expect(second.createdFiles).toEqual([]);
  });

  it("keeps a blank file the kit did not create", async () => {
    write(".mcp.json", "{}\n");
    const a = await stage([{ kind: "mergeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"], value: 1 }], opts());
    commit(a, scopeRoot, backupDir);
    const b = await stage([{ kind: "removeJson", module: "m", target: ".mcp.json", path: ["mcpServers", "a"] }], opts(keep, a.createdFiles));
    commit(b, scopeRoot, join(root, ".harness-kit/backup/t2"));
    expect(read(".mcp.json")).toBe("{}\n");
  });

  it("asks before deleting an owned file the user modified", async () => {
    write("a.txt", "user edit");
    const del: Operation[] = [{ kind: "deleteOwned", module: "m", target: "a.txt", expectedHash: hashContent("v1") }];
    expect((await stage(del, opts(keep))).writes).toEqual([]);
    expect((await stage(del, opts(overwrite))).writes).toEqual([{ target: "a.txt", before: "user edit", after: null }]);
  });

  it("aborts the whole plan before writing when a JSON target cannot be parsed", async () => {
    write(".claude/settings.json", "{ broken");
    const ops: Operation[] = [
      { kind: "writeOwned", module: "m", target: "a.txt", content: "a" },
      { kind: "mergeJson", module: "m", target: ".claude/settings.json", path: ["hooks", "Stop"], value: {}, match: { commandContains: "x" } },
    ];
    await expect(stage(ops, opts())).rejects.toThrowError(/cannot parse \.claude\/settings\.json/);
    expect(existsSync(join(root, "a.txt"))).toBe(false);
  });

  it("rolls back every write when one fails", async () => {
    write("a.txt", "v1");
    const staged = await stage([
      { kind: "writeOwned", module: "m", target: "a.txt", content: "v2", expectedHash: hashContent("v1") },
      { kind: "writeOwned", module: "m", target: "new/b.txt", content: "b" },
      { kind: "writeOwned", module: "m", target: "c.txt", content: "c" },
    ], opts());
    expect(() => commit(staged, scopeRoot, backupDir, (target) => {
      if (target === "c.txt") throw new Error("disk full");
    })).toThrowError(/disk full/);
    expect(read("a.txt")).toBe("v1");
    expect(existsSync(join(root, "new"))).toBe(false);
    expect(existsSync(join(root, "c.txt"))).toBe(false);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/executor.test.ts`
Expected: FAIL — cannot resolve `../src/executor.js`.

- [ ] **Step 3: Implement `src/executor.ts`**

```ts
import {
  lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, rmdirSync, rmSync, writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import { KitError } from "./errors.js";
import { hashContent } from "./hash.js";
import { isEmptyJson, removeJsonEntry, toPointer, upsertJsonEntry } from "./ops/json-merge.js";
import { removeBlock, upsertBlock } from "./ops/marked-block.js";
import type { Operation, Owned } from "./types.js";

export interface ScopeRoot { root: string; allowed: string[] }
export interface Conflict { target: string; reason: "modified" | "unowned"; current: string; incoming: string | null }
export interface StageOptions {
  scopeRoot: ScopeRoot;
  createdFiles: string[];
  onConflict: (conflict: Conflict) => Promise<"keep" | "overwrite">;
}
export interface StagedWrite { target: string; before: string | null; after: string | null }
export interface ModuleRecord { owned: Owned; scaffolded: string[] }
export interface Staged {
  writes: StagedWrite[];
  records: Record<string, ModuleRecord>;
  createdFiles: string[];
  warnings: string[];
}

function lstatExists(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

export function resolveConfined(scopeRoot: ScopeRoot, target: string): string {
  const segments = target.split("/");
  if (target === "" || isAbsolute(target) || target.includes("\\") || segments.includes("..") || segments.includes("")) {
    throw new KitError(`unsafe target path: ${JSON.stringify(target)}`);
  }
  if (segments[0] === ".git" || segments[0] === ".harness-kit") {
    throw new KitError(`target inside a protected directory: ${target}`);
  }
  const allowed = scopeRoot.allowed.some((prefix) =>
    prefix === "" || (prefix.endsWith("/") ? target.startsWith(prefix) : target === prefix));
  if (!allowed) throw new KitError(`target outside allowed locations: ${target}`);

  const root = realpathSync(scopeRoot.root);
  const absolute = resolve(root, target);
  let probe = absolute;
  while (!lstatExists(probe)) probe = dirname(probe);
  let real: string;
  try {
    real = realpathSync(probe);
  } catch {
    throw new KitError(`target passes through a broken symlink: ${target}`);
  }
  if (real !== root && !real.startsWith(root + sep)) {
    throw new KitError(`target escapes ${scopeRoot.root} through a symlink: ${target}`);
  }
  return absolute;
}

const isBlank = (target: string, content: string): boolean =>
  target.endsWith(".json") ? isEmptyJson(content) : content.trim() === "";

export async function stage(ops: Operation[], options: StageOptions): Promise<Staged> {
  const state = new Map<string, { before: string | null; current: string | null }>();
  const records: Record<string, ModuleRecord> = {};
  const created = new Set<string>();
  const touchedByRemoval = new Set<string>();
  const warnings: string[] = [];

  const load = (target: string) => {
    let entry = state.get(target);
    if (!entry) {
      const absolute = resolveConfined(options.scopeRoot, target);
      let before: string | null = null;
      if (lstatExists(absolute)) {
        try {
          before = readFileSync(absolute, "utf8");
        } catch (err) {
          throw new KitError(`cannot read ${target}: ${(err as Error).message}`);
        }
      }
      entry = { before, current: before };
      state.set(target, entry);
    }
    return entry;
  };
  const record = (module: string) =>
    (records[module] ??= { owned: { files: [], json: [], blocks: [] }, scaffolded: [] });

  for (const op of ops) {
    const file = load(op.target);
    const rec = record(op.module);
    switch (op.kind) {
      case "writeOwned": {
        const owned = { path: op.target, hash: hashContent(op.content) };
        if (file.current === null || file.current === op.content) {
          file.current = op.content;
          rec.owned.files.push(owned);
        } else if (op.expectedHash !== undefined && hashContent(file.current) === op.expectedHash) {
          file.current = op.content;
          rec.owned.files.push(owned);
        } else {
          const reason = op.expectedHash !== undefined ? "modified" : "unowned";
          const decision = await options.onConflict({ target: op.target, reason, current: file.current, incoming: op.content });
          if (decision === "overwrite") {
            file.current = op.content;
            rec.owned.files.push(owned);
          } else {
            warnings.push(`kept your version of ${op.target}`);
            if (reason === "modified") rec.owned.files.push(owned);
          }
        }
        break;
      }
      case "scaffoldOnce":
        if (file.current === null) {
          file.current = op.content;
          rec.scaffolded.push(op.target);
        }
        break;
      case "mergeJson":
        if (file.current === null) created.add(op.target);
        file.current = upsertJsonEntry(file.current ?? "", op.target, op.path, op.value, op.match);
        rec.owned.json.push({ file: op.target, pointer: toPointer(op.path), ...(op.match ? { match: op.match } : {}) });
        break;
      case "markedBlock":
        if (file.current === null) created.add(op.target);
        file.current = upsertBlock(file.current ?? "", op.id, op.content);
        rec.owned.blocks.push({ file: op.target, id: op.id });
        break;
      case "deleteOwned":
        if (file.current === null) break;
        if (hashContent(file.current) === op.expectedHash) {
          file.current = null;
        } else {
          const decision = await options.onConflict({ target: op.target, reason: "modified", current: file.current, incoming: null });
          if (decision === "overwrite") file.current = null;
          else warnings.push(`kept your version of ${op.target}`);
        }
        break;
      case "removeJson":
        if (file.current !== null) {
          file.current = removeJsonEntry(file.current, op.target, op.path, op.match);
          touchedByRemoval.add(op.target);
        }
        break;
      case "removeBlock":
        if (file.current !== null) {
          file.current = removeBlock(file.current, op.id);
          touchedByRemoval.add(op.target);
        }
        break;
    }
  }

  const createdFiles = new Set([...options.createdFiles, ...created]);
  for (const target of touchedByRemoval) {
    const file = state.get(target)!;
    if (createdFiles.has(target) && file.current !== null && isBlank(target, file.current)) {
      file.current = null;
      createdFiles.delete(target);
    }
  }

  const writes: StagedWrite[] = [];
  for (const [target, file] of state) {
    if (file.before !== file.current) writes.push({ target, before: file.before, after: file.current });
  }
  return { writes, records, createdFiles: [...createdFiles].sort(), warnings };
}

function pruneEmptyDirs(from: string, root: string): void {
  let dir = from;
  while (dir !== root && dir.startsWith(root + sep)) {
    try {
      if (readdirSync(dir).length > 0) return;
      rmdirSync(dir);
    } catch {
      return;
    }
    dir = dirname(dir);
  }
}

function put(absolute: string, content: string | null, root: string): void {
  if (content === null) {
    rmSync(absolute, { force: true });
    pruneEmptyDirs(dirname(absolute), root);
    return;
  }
  mkdirSync(dirname(absolute), { recursive: true });
  const temp = `${absolute}.kit-tmp`;
  writeFileSync(temp, content, "utf8");
  renameSync(temp, absolute);
}

export function commit(staged: Staged, scopeRoot: ScopeRoot, backupDir: string, onWrite?: (target: string) => void): void {
  const root = realpathSync(scopeRoot.root);
  const done: StagedWrite[] = [];
  try {
    for (const w of staged.writes) {
      const absolute = resolveConfined(scopeRoot, w.target);
      if (w.before !== null) {
        const backup = join(backupDir, w.target);
        mkdirSync(dirname(backup), { recursive: true });
        writeFileSync(backup, w.before, "utf8");
      }
      onWrite?.(w.target);
      done.push(w);
      put(absolute, w.after, root);
    }
  } catch (err) {
    for (const w of done.reverse()) put(resolve(root, w.target), w.before, root);
    throw err;
  }
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `npx vitest run test/executor.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/executor.ts test/executor.test.ts
git commit -m "feat: executor with path confinement, staging, rollback"
```

---

### Task 6: Kit state — paths, lockfile, user config

**Files:**
- Create: `src/paths.ts`, `src/lockfile.ts`, `src/userconfig.ts`
- Test: `test/state.test.ts`

**Interfaces:**
- Consumes: `Lockfile`, `CatalogSource`, `Scope`; `KitError`.
- Produces:
  - `findProjectRoot(cwd: string): string` — nearest ancestor containing `.harness-kit/lock.json` or `.git`; otherwise `cwd`.
  - `userStateDir(home: string): string` → `<home>/.config/harness-kit`
  - `catalogCacheDir(home: string): string` → `<home>/.cache/harness-kit/catalogs`
  - `lockPath(scope: Scope, projectRoot: string, home: string): string`
  - `backupRoot(scope: Scope, projectRoot: string, home: string): string`
  - `moduleStateDir(home: string, module: string): string` → `<home>/.config/harness-kit/state/<module>`
  - `emptyLock(harness?: string): Lockfile`; `readLock(path: string): Lockfile` (missing file → empty lock); `writeLock(path: string, lock: Lockfile): void` (atomic; also writes a `.gitignore` containing `backup/` when the lock lives in a `.harness-kit` directory).
  - `readUserConfig(home: string): { catalogs: CatalogSource[] }`; `writeUserConfig(home: string, config: { catalogs: CatalogSource[] }): void`
  - `sourceKey(source: CatalogSource): string` — identity of a catalog source: `"<url>#<subdir or empty>"`.

- [ ] **Step 1: Write the failing test**

`test/state.test.ts`:
```ts
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { emptyLock, readLock, writeLock } from "../src/lockfile.js";
import { backupRoot, catalogCacheDir, findProjectRoot, lockPath, moduleStateDir } from "../src/paths.js";
import { readUserConfig, sourceKey, writeUserConfig } from "../src/userconfig.js";

const tmp = () => mkdtempSync(join(tmpdir(), "kit-state-"));

describe("paths", () => {
  it("places project state in the repo and user state under ~/.config/harness-kit", () => {
    expect(lockPath("project", "/repo", "/home/u")).toBe("/repo/.harness-kit/lock.json");
    expect(lockPath("user", "/repo", "/home/u")).toBe("/home/u/.config/harness-kit/lock.json");
    expect(backupRoot("project", "/repo", "/home/u")).toBe("/repo/.harness-kit/backup");
    expect(backupRoot("user", "/repo", "/home/u")).toBe("/home/u/.config/harness-kit/backup");
    expect(catalogCacheDir("/home/u")).toBe("/home/u/.cache/harness-kit/catalogs");
    expect(moduleStateDir("/home/u", "budget-guard")).toBe("/home/u/.config/harness-kit/state/budget-guard");
  });

  it("finds the project root from a nested directory", () => {
    const repo = tmp();
    mkdirSync(join(repo, ".git"));
    mkdirSync(join(repo, "src/deep"), { recursive: true });
    expect(findProjectRoot(join(repo, "src/deep"))).toBe(repo);
    const loose = tmp();
    expect(findProjectRoot(loose)).toBe(loose);
  });
});

describe("lockfile", () => {
  it("returns an empty lock when the file is missing", () => {
    expect(readLock(join(tmp(), "lock.json"))).toEqual(emptyLock());
    expect(emptyLock()).toEqual({ lockVersion: 1, harness: "claude-code", catalogs: {}, createdFiles: [], modules: {} });
  });

  it("round-trips and writes a .gitignore next to a project lock", () => {
    const repo = tmp();
    const path = lockPath("project", repo, "/nowhere");
    const lock = { ...emptyLock(), profile: "dev", createdFiles: [".mcp.json"] };
    writeLock(path, lock);
    expect(readLock(path)).toEqual(lock);
    expect(readFileSync(path, "utf8").endsWith("}\n")).toBe(true);
    expect(readFileSync(join(repo, ".harness-kit/.gitignore"), "utf8")).toBe("backup/\n");
  });

  it("does not write a .gitignore for the user lock", () => {
    const home = tmp();
    writeLock(lockPath("user", "/repo", home), emptyLock());
    expect(() => readFileSync(join(home, ".config/harness-kit/.gitignore"))).toThrow();
  });

  it("rejects an unreadable or future lockfile", () => {
    const dir = tmp();
    writeFileSync(join(dir, "bad.json"), "{ nope");
    expect(() => readLock(join(dir, "bad.json"))).toThrowError(/bad\.json/);
    writeFileSync(join(dir, "future.json"), JSON.stringify({ ...emptyLock(), lockVersion: 2 }));
    expect(() => readLock(join(dir, "future.json"))).toThrowError(/lockVersion 2.*newer version of kit/);
  });
});

describe("user config", () => {
  it("defaults to no catalogs and round-trips", () => {
    const home = tmp();
    expect(readUserConfig(home)).toEqual({ catalogs: [] });
    writeUserConfig(home, { catalogs: [{ url: "git@internal:agents/catalog.git", ref: "main" }] });
    expect(readUserConfig(home).catalogs[0]!.url).toBe("git@internal:agents/catalog.git");
  });

  it("identifies a source by url and subdirectory, not ref", () => {
    expect(sourceKey({ url: "u", ref: "main" })).toBe("u#");
    expect(sourceKey({ url: "u", subdir: "catalog" })).toBe("u#catalog");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/state.test.ts`
Expected: FAIL — cannot resolve `../src/lockfile.js`.

- [ ] **Step 3: Implement the three files**

`src/paths.ts`:
```ts
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Scope } from "./types.js";

export function findProjectRoot(cwd: string): string {
  let dir = cwd;
  for (;;) {
    if (existsSync(join(dir, ".harness-kit", "lock.json")) || existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return cwd;
    dir = parent;
  }
}

export const userStateDir = (home: string): string => join(home, ".config", "harness-kit");
export const catalogCacheDir = (home: string): string => join(home, ".cache", "harness-kit", "catalogs");
export const moduleStateDir = (home: string, module: string): string => join(userStateDir(home), "state", module);

const stateDir = (scope: Scope, projectRoot: string, home: string): string =>
  scope === "project" ? join(projectRoot, ".harness-kit") : userStateDir(home);

export const lockPath = (scope: Scope, projectRoot: string, home: string): string =>
  join(stateDir(scope, projectRoot, home), "lock.json");

export const backupRoot = (scope: Scope, projectRoot: string, home: string): string =>
  join(stateDir(scope, projectRoot, home), "backup");
```

`src/lockfile.ts`:
```ts
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { KitError } from "./errors.js";
import type { Lockfile } from "./types.js";

export function emptyLock(harness = "claude-code"): Lockfile {
  return { lockVersion: 1, harness, catalogs: {}, createdFiles: [], modules: {} };
}

export function readLock(path: string): Lockfile {
  if (!existsSync(path)) return emptyLock();
  let raw: Partial<Lockfile>;
  try {
    raw = JSON.parse(readFileSync(path, "utf8")) as Partial<Lockfile>;
  } catch (err) {
    throw new KitError(`cannot read lockfile ${path}: ${(err as Error).message}`);
  }
  if (raw.lockVersion !== 1) {
    throw new KitError(`${path} has lockVersion ${String(raw.lockVersion)}; it was written by a newer version of kit`);
  }
  return { ...emptyLock(raw.harness), ...raw } as Lockfile;
}

export function writeLock(path: string, lock: Lockfile): void {
  const dir = dirname(path);
  mkdirSync(dir, { recursive: true });
  const temp = `${path}.kit-tmp`;
  writeFileSync(temp, JSON.stringify(lock, null, 2) + "\n", "utf8");
  renameSync(temp, path);
  const gitignore = join(dir, ".gitignore");
  if (basename(dir) === ".harness-kit" && !existsSync(gitignore)) writeFileSync(gitignore, "backup/\n", "utf8");
}
```

`src/userconfig.ts`:
```ts
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
```

- [ ] **Step 4: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paths.ts src/lockfile.ts src/userconfig.ts test/state.test.ts
git commit -m "feat: kit state paths, lockfile, user config"
```

---
### Task 7: Claude Code hook runtime shim

`assets/claude-code/runtime.mjs` is plain JavaScript that the adapter copies to `<scope>/.claude/kit/runtime.mjs`. Module hook scripts live at `<scope>/.claude/kit/hooks/<module>/<script>` and import it as `../../runtime.mjs`. It must have **no dependencies** beyond Node built-ins, because it runs inside other people's projects.

**Files:**
- Create: `assets/claude-code/runtime.mjs`
- Test: `test/runtime.test.ts`

**Interfaces:**
- Consumes: at run time, `<kitDir>/config/<module>.json` with shape `{ module: string, version: string, scope: "project" | "user", onError: Record<string, "allow" | "deny">, values: Record<string, unknown> }` (written by the adapter in Task 8; `onError` is keyed by script path relative to the module's `hooks/` folder, e.g. `"check.mjs"`).
- Produces: `run(handler)` where `handler` receives `{ event, tool, session, config, raw, allow, warn, ask, deny }`:
  - `event`: neutral event name (`"pre-tool-use"`, …) or the raw name if unknown
  - `tool`: `{ kind: "subagent" | "shell" | "edit" | "other", name: string, input: object }`, or `null` for non-tool events
  - `session`: `{ id: string, cwd: string, transcriptPath: string | null }`
  - `config`: the `values` object
  - `allow()`, `warn(message)`, `ask(reason)`, `deny(reason)` — return the outcome from the handler. Returning nothing means allow.
- Claude Code output encoding: `allow` → exit 0, no output (never emits `permissionDecision: "allow"`, which would bypass the user's permission prompts). `warn` → `{"systemMessage": …}`. `ask` → PreToolUse `permissionDecision: "ask"`; on any other event it is treated as `deny`. `deny` → PreToolUse `permissionDecision: "deny"`; UserPromptSubmit `{"decision":"block","reason":…}`; any other event: reason on stderr, exit code 2.

- [ ] **Step 1: Write the failing test**

`test/runtime.test.ts`:
```ts
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { tempDir } from "./helpers.js";

const RUNTIME = join(import.meta.dirname, "../assets/claude-code/runtime.mjs");
const HOOK = `import { run } from "../../runtime.mjs";
run((ctx) => {
  const b = ctx.config.behavior;
  if (b === "throw") throw new Error("boom");
  if (b === "nothing") return;
  return ctx[b](\`\${b}:\${ctx.event}:\${ctx.tool?.kind}:\${ctx.session.id}\`);
});
`;

let kitDir: string;
let projectDir: string;

function runHook(behavior: string, payload: object, extra: { scope?: string; onError?: "allow" | "deny" } = {}) {
  writeFileSync(join(kitDir, "config/demo.json"), JSON.stringify({
    module: "demo", version: "1.0.0", scope: extra.scope ?? "project",
    onError: { "h.mjs": extra.onError ?? "allow" }, values: { behavior },
  }));
  const result = spawnSync(process.execPath, [join(kitDir, "hooks/demo/h.mjs")], {
    input: JSON.stringify({ session_id: "s1", cwd: projectDir, transcript_path: "/t.jsonl", ...payload }),
    encoding: "utf8",
  });
  return { code: result.status, stdout: result.stdout.trim(), stderr: result.stderr };
}

const PRE_BASH = { hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: { command: "ls" } };

beforeEach(() => {
  const root = tempDir("kit-runtime-");
  kitDir = join(root, "kit");
  projectDir = join(root, "project");
  mkdirSync(join(kitDir, "hooks/demo"), { recursive: true });
  mkdirSync(join(kitDir, "config"), { recursive: true });
  mkdirSync(projectDir, { recursive: true });
  copyFileSync(RUNTIME, join(kitDir, "runtime.mjs"));
  writeFileSync(join(kitDir, "hooks/demo/h.mjs"), HOOK);
});

describe("claude-code hook runtime", () => {
  it("allow exits 0 silently, and so does returning nothing", () => {
    expect(runHook("allow", PRE_BASH)).toMatchObject({ code: 0, stdout: "" });
    expect(runHook("nothing", PRE_BASH)).toMatchObject({ code: 0, stdout: "" });
  });

  it("deny on PreToolUse emits a deny decision with normalized context", () => {
    const r = runHook("deny", PRE_BASH);
    expect(r.code).toBe(0);
    expect(JSON.parse(r.stdout)).toEqual({ hookSpecificOutput: {
      hookEventName: "PreToolUse", permissionDecision: "deny",
      permissionDecisionReason: "deny:pre-tool-use:shell:s1" } });
  });

  it("maps the Agent tool to the subagent kind and ask to an ask decision", () => {
    const r = runHook("ask", { hook_event_name: "PreToolUse", tool_name: "Agent", tool_input: { model: "opus" } });
    expect(JSON.parse(r.stdout).hookSpecificOutput).toMatchObject({
      permissionDecision: "ask", permissionDecisionReason: "ask:pre-tool-use:subagent:s1" });
  });

  it("warn emits a systemMessage", () => {
    const r = runHook("warn", { hook_event_name: "SessionStart" });
    expect(JSON.parse(r.stdout)).toEqual({ systemMessage: "warn:session-start:undefined:s1" });
  });

  it("deny blocks a user prompt, and exits 2 on events without a decision format", () => {
    expect(JSON.parse(runHook("deny", { hook_event_name: "UserPromptSubmit" }).stdout))
      .toEqual({ decision: "block", reason: "deny:user-prompt:undefined:s1" });
    const stop = runHook("deny", { hook_event_name: "Stop" });
    expect(stop.code).toBe(2);
    expect(stop.stderr).toContain("deny:stop:undefined:s1");
  });

  it("ask outside PreToolUse is treated as deny", () => {
    expect(JSON.parse(runHook("ask", { hook_event_name: "UserPromptSubmit" }).stdout).decision).toBe("block");
  });

  it("a crashing hook fails open by default and closed when onError is deny", () => {
    const open = runHook("throw", PRE_BASH);
    expect(open).toMatchObject({ code: 0, stdout: "" });
    expect(open.stderr).toContain("[kit:demo] hook error");
    expect(open.stderr).toContain("boom");
    const closed = runHook("throw", PRE_BASH, { onError: "deny" });
    expect(JSON.parse(closed.stdout).hookSpecificOutput.permissionDecision).toBe("deny");
  });

  it("a user-scope hook yields when the project has the same module installed", () => {
    mkdirSync(join(projectDir, ".harness-kit"));
    writeFileSync(join(projectDir, ".harness-kit/lock.json"), JSON.stringify({ modules: { demo: {} } }));
    expect(runHook("deny", PRE_BASH, { scope: "user" })).toMatchObject({ code: 0, stdout: "" });
    expect(runHook("deny", PRE_BASH, { scope: "project" }).stdout).toContain("deny");
  });
});
```

This test imports `tempDir` from `test/helpers.ts`, which Task 10 extends. Create the file now with just that function:

`test/helpers.ts`:
```ts
import { mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** A fresh temp directory, realpath'd (on macOS /tmp is a symlink). */
export function tempDir(prefix = "kit-"): string {
  return realpathSync(mkdtempSync(join(tmpdir(), prefix)));
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/runtime.test.ts`
Expected: FAIL — `copyFileSync` cannot find `assets/claude-code/runtime.mjs`.

- [ ] **Step 3: Implement `assets/claude-code/runtime.mjs`**

```js
// Harness Kit hook runtime for Claude Code. Copied into <scope>/.claude/kit/ and owned by the kit.
// Node built-ins only: this file runs inside other people's projects.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const KIT_DIR = dirname(fileURLToPath(import.meta.url));

const EVENTS = {
  PreToolUse: "pre-tool-use", PostToolUse: "post-tool-use", SessionStart: "session-start",
  UserPromptSubmit: "user-prompt", SubagentStart: "subagent-start", Stop: "stop",
};
const TOOL_KINDS = {
  Agent: "subagent", Task: "subagent", Bash: "shell",
  Edit: "edit", Write: "edit", MultiEdit: "edit", NotebookEdit: "edit",
};

class Outcome {
  constructor(type, message) {
    this.type = type;
    this.message = message === undefined ? "" : String(message);
  }
}
const allow = () => new Outcome("allow");
const warn = (message) => new Outcome("warn", message);
const ask = (reason) => new Outcome("ask", reason);
const deny = (reason) => new Outcome("deny", reason);

function projectHasModule(cwd, moduleName) {
  let dir = resolve(cwd);
  for (;;) {
    const lock = join(dir, ".harness-kit", "lock.json");
    if (existsSync(lock)) {
      try {
        return Boolean(JSON.parse(readFileSync(lock, "utf8")).modules?.[moduleName]);
      } catch {
        return false;
      }
    }
    const parent = dirname(dir);
    if (parent === dir) return false;
    dir = parent;
  }
}

function emit(outcome, rawEvent) {
  const print = (value) => process.stdout.write(JSON.stringify(value) + "\n");
  const preTool = (decision) => print({ hookSpecificOutput: {
    hookEventName: "PreToolUse", permissionDecision: decision, permissionDecisionReason: outcome.message } });

  if (outcome.type === "allow") return 0;
  if (outcome.type === "warn") {
    print({ systemMessage: outcome.message });
    return 0;
  }
  if (rawEvent === "PreToolUse") {
    preTool(outcome.type === "ask" ? "ask" : "deny");
    return 0;
  }
  if (rawEvent === "UserPromptSubmit") {
    print({ decision: "block", reason: outcome.message });
    return 0;
  }
  process.stderr.write(outcome.message + "\n");
  return 2;
}

export async function run(handler) {
  const script = resolve(process.argv[1]);
  const [moduleName, ...rest] = relative(join(KIT_DIR, "hooks"), script).split(sep);
  const scriptKey = rest.join("/");
  let settings = { scope: "project", onError: {}, values: {} };
  let raw = {};
  let outcome;
  try {
    settings = JSON.parse(readFileSync(join(KIT_DIR, "config", `${moduleName}.json`), "utf8"));
    raw = JSON.parse(readFileSync(0, "utf8") || "{}");
    const cwd = raw.cwd ?? process.cwd();
    if (settings.scope === "user" && projectHasModule(cwd, moduleName)) {
      outcome = allow(); // the project install of this module wins
    } else {
      const result = await handler({
        event: EVENTS[raw.hook_event_name] ?? raw.hook_event_name,
        tool: raw.tool_name
          ? { kind: TOOL_KINDS[raw.tool_name] ?? "other", name: raw.tool_name, input: raw.tool_input ?? {} }
          : null,
        session: { id: raw.session_id ?? "", cwd, transcriptPath: raw.transcript_path ?? null },
        config: settings.values ?? {},
        raw,
        allow, warn, ask, deny,
      });
      outcome = result instanceof Outcome ? result : allow();
    }
  } catch (error) {
    process.stderr.write(`[kit:${moduleName}] hook error: ${error?.stack ?? error}\n`);
    outcome = settings.onError?.[scriptKey] === "deny"
      ? deny(`kit hook ${moduleName}/${scriptKey} failed: ${error?.message ?? error}`)
      : allow();
  }
  process.exitCode = emit(outcome, raw.hook_event_name);
}
```

- [ ] **Step 4: Run tests**

Run: `npx vitest run test/runtime.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assets/claude-code/runtime.mjs test/runtime.test.ts test/helpers.ts
git commit -m "feat: Claude Code hook runtime shim"
```

---

### Task 8: Adapter interface and the Claude Code adapter

**Files:**
- Create: `src/adapters/adapter.ts`, `src/adapters/claude-code.ts`
- Test: `test/claude-code-adapter.test.ts`

**Interfaces:**
- Consumes: `ModuleDef`, `Operation`, `Capability`, `Scope`, `CAPABILITIES`; `renderTemplate`, `templateVars`; `KitError`; the asset `assets/claude-code/runtime.mjs` (read once, lazily — the only file access an adapter performs).
- Produces:
  - `interface AdapterEnv { home: string }`
  - `interface HarnessAdapter { id: string; capabilities(): Capability[]; allowedPrefixes(scope: Scope): string[]; translate(def: ModuleDef, config: Record<string, unknown>, scope: Scope, env: AdapterEnv): Operation[] }` — `config` is already validated and defaulted by the planner.
  - `getAdapter(id: string): HarnessAdapter` — throws `KitError` for unknown ids.
  - `claudeCodeAdapter: HarnessAdapter`
- Target layout (relative to the scope root — the repo at project scope, the home directory at user scope):

| Contribution | Project scope | User scope |
|---|---|---|
| Skill files | `.claude/skills/<skill>/…` | same |
| Runtime shim | `.claude/kit/runtime.mjs` | same |
| Every file under the module's `hooks/` | `.claude/kit/hooks/<module>/…` | same |
| Module config | `.claude/kit/config/<module>.json` | same |
| Hook registration | `mergeJson` into `.claude/settings.json` at `["hooks", <Event>]` | same |
| MCP servers | `mergeJson` into `.mcp.json` at `["mcpServers", <name>]` | into `.claude.json` |
| Instructions | `markedBlock` id `<module>` in `CLAUDE.md` | in `.claude/CLAUDE.md` |
| Scaffold | `scaffoldOnce` at `<to>/…` | not emitted |

- [ ] **Step 1: Write the failing test**

`test/claude-code-adapter.test.ts`:
```ts
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { getAdapter } from "../src/adapters/adapter.js";
import { loadCatalog, resolveModule } from "../src/catalog/load.js";
import { CAPABILITIES, type Operation } from "../src/types.js";

const catalogs = [
  loadCatalog(join(import.meta.dirname, "fixtures/catalog")),
  loadCatalog(join(import.meta.dirname, "fixtures/company-catalog")),
];
const adapter = getAdapter("claude-code");
const env = { home: "/home/u" };
const byKind = <K extends Operation["kind"]>(ops: Operation[], kind: K) =>
  ops.filter((o): o is Extract<Operation, { kind: K }> => o.kind === kind);

describe("claude-code adapter", () => {
  it("reports every capability and rejects unknown adapters", () => {
    expect(adapter.capabilities()).toEqual([...CAPABILITIES]);
    expect(() => getAdapter("emacs")).toThrowError(/unknown harness "emacs".*claude-code/);
  });

  it("confines user scope to Claude Code's own files", () => {
    expect(adapter.allowedPrefixes("project")).toEqual([""]);
    expect(adapter.allowedPrefixes("user")).toEqual([".claude/", ".claude.json"]);
  });

  const alpha = resolveModule(catalogs, "alpha");
  const ops = adapter.translate(alpha, { greeting: "hi", areas: ["api", "fw"] }, "project", env);

  it("copies skills, hook scripts, the runtime, and a config file", () => {
    const owned = byKind(ops, "writeOwned");
    expect(owned.map((o) => o.target)).toEqual([
      ".claude/skills/alpha-skill/SKILL.md",
      ".claude/kit/runtime.mjs",
      ".claude/kit/hooks/alpha/check.mjs",
      ".claude/kit/hooks/alpha/start.mjs",
      ".claude/kit/config/alpha.json",
    ]);
    expect(owned[0]!.content).toBe(alpha.files["skills/alpha-skill/SKILL.md"]);
    expect(owned[1]!.content).toContain("export async function run");
    expect(JSON.parse(owned[4]!.content)).toEqual({
      module: "alpha", version: "1.0.0", scope: "project",
      onError: { "check.mjs": "allow", "start.mjs": "deny" },
      values: { greeting: "hi", areas: ["api", "fw"] },
    });
    expect(owned.every((o) => o.module === "alpha")).toBe(true);
  });

  it("registers hooks with Claude Code event and tool names", () => {
    const settings = byKind(ops, "mergeJson").filter((o) => o.target === ".claude/settings.json");
    expect(settings).toEqual([
      { kind: "mergeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "PreToolUse"],
        value: { matcher: "Bash", hooks: [{ type: "command",
          command: 'node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/check.mjs' }] },
        match: { commandContains: "kit/hooks/alpha/check.mjs" } },
      { kind: "mergeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "SessionStart"],
        value: { hooks: [{ type: "command",
          command: 'node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/start.mjs' }] },
        match: { commandContains: "kit/hooks/alpha/start.mjs" } },
    ]);
  });

  it("merges MCP servers, renders instructions into a block, and scaffolds", () => {
    expect(byKind(ops, "mergeJson").find((o) => o.target === ".mcp.json")).toEqual({
      kind: "mergeJson", module: "alpha", target: ".mcp.json", path: ["mcpServers", "alpha-mcp"],
      value: { command: "alpha-mcp", env: { TOKEN: "${ALPHA_TOKEN}" } } });
    expect(byKind(ops, "markedBlock")).toEqual([{
      kind: "markedBlock", module: "alpha", target: "CLAUDE.md", id: "alpha",
      content: '## Alpha\n\nGreeting is "hi". Areas: api, fw.' }]);
    expect(byKind(ops, "scaffoldOnce")).toEqual([{
      kind: "scaffoldOnce", module: "alpha", target: "docs/context/INDEX.md",
      content: "# Context index (alpha 1.0.0)\n\nAreas: api, fw\n" }]);
  });

  it("uses absolute commands and user-level files at user scope", () => {
    const beta = resolveModule(catalogs, "beta");
    const userOps = adapter.translate(beta, { mode: "warn" }, "user", env);
    const hook = byKind(userOps, "mergeJson")[0]!;
    expect(hook.value).toEqual({ matcher: "Agent", hooks: [{ type: "command",
      command: 'node "/home/u/.claude/kit/hooks/beta/guard.mjs"' }] });
    expect(JSON.parse(byKind(userOps, "writeOwned").at(-1)!.content).scope).toBe("user");
  });

  it("emits no runtime or config for a module without hooks", () => {
    const gamma = resolveModule(catalogs, "gamma");
    const gammaOps = adapter.translate(gamma, {}, "project", env);
    expect(gammaOps.map((o) => o.kind)).toEqual(["markedBlock"]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/claude-code-adapter.test.ts`
Expected: FAIL — cannot resolve `../src/adapters/adapter.js`.

- [ ] **Step 3: Implement `src/adapters/adapter.ts`**

```ts
import { KitError } from "../errors.js";
import type { Capability, ModuleDef, Operation, Scope } from "../types.js";
import { claudeCodeAdapter } from "./claude-code.js";

export interface AdapterEnv { home: string }

export interface HarnessAdapter {
  id: string;
  capabilities(): Capability[];
  /** Relative prefixes the executor may write to. "" = whole root, "dir/" = subtree, otherwise an exact file. */
  allowedPrefixes(scope: Scope): string[];
  /** Pure: turns a module into operations. `config` is already validated and defaulted. */
  translate(def: ModuleDef, config: Record<string, unknown>, scope: Scope, env: AdapterEnv): Operation[];
}

const ADAPTERS: Record<string, HarnessAdapter> = { "claude-code": claudeCodeAdapter };

export function getAdapter(id: string): HarnessAdapter {
  const adapter = ADAPTERS[id];
  if (!adapter) throw new KitError(`unknown harness "${id}"; available: ${Object.keys(ADAPTERS).join(", ")}`);
  return adapter;
}
```

- [ ] **Step 4: Implement `src/adapters/claude-code.ts`**

```ts
import { readFileSync } from "node:fs";
import { renderTemplate, templateVars } from "../template.js";
import { CAPABILITIES, type HookEvent, type ModuleDef, type Operation, type Scope, type ToolMatcher } from "../types.js";
import type { AdapterEnv, HarnessAdapter } from "./adapter.js";

const EVENT_NAMES: Record<HookEvent, string> = {
  "pre-tool-use": "PreToolUse", "post-tool-use": "PostToolUse", "session-start": "SessionStart",
  "user-prompt": "UserPromptSubmit", "subagent-start": "SubagentStart", "stop": "Stop",
};
const TOOL_NAMES: Record<ToolMatcher, string | undefined> = {
  "*": undefined, subagent: "Agent", shell: "Bash", edit: "Edit|Write",
};
const TOOL_EVENTS: HookEvent[] = ["pre-tool-use", "post-tool-use"];

let runtimeSource: string | undefined;
function runtime(): string {
  // Same relative depth from src/adapters/ and dist/adapters/.
  runtimeSource ??= readFileSync(new URL("../../assets/claude-code/runtime.mjs", import.meta.url), "utf8");
  return runtimeSource;
}

const under = (def: ModuleDef, dir: string): string[] =>
  Object.keys(def.files).filter((f) => f.startsWith(dir + "/")).sort();

function translate(def: ModuleDef, config: Record<string, unknown>, scope: Scope, env: AdapterEnv): Operation[] {
  const module = def.name;
  const vars = templateVars(def, config);
  const ops: Operation[] = [];

  for (const skill of def.contributes.skills) {
    const skillName = skill.split("/").at(-1)!;
    for (const file of under(def, skill)) {
      ops.push({ kind: "writeOwned", module, target: `.claude/skills/${skillName}/${file.slice(skill.length + 1)}`,
                 content: def.files[file]! });
    }
  }

  if (def.contributes.hooks.length > 0) {
    ops.push({ kind: "writeOwned", module, target: ".claude/kit/runtime.mjs", content: runtime() });
    for (const file of under(def, "hooks")) {
      ops.push({ kind: "writeOwned", module, target: `.claude/kit/hooks/${module}/${file.slice("hooks/".length)}`,
                 content: def.files[file]! });
    }
    const onError: Record<string, string> = {};
    for (const hook of def.contributes.hooks) onError[hook.run.slice("hooks/".length)] = hook.onError;
    ops.push({ kind: "writeOwned", module, target: `.claude/kit/config/${module}.json`,
               content: JSON.stringify({ module, version: def.version, scope, onError, values: config }, null, 2) + "\n" });

    for (const hook of def.contributes.hooks) {
      const script = `kit/hooks/${module}/${hook.run.slice("hooks/".length)}`;
      const command = scope === "project"
        ? `node "$CLAUDE_PROJECT_DIR"/.claude/${script}`
        : `node "${env.home.replace(/\\/g, "/")}/.claude/${script}"`;
      const matcher = TOOL_EVENTS.includes(hook.event) ? TOOL_NAMES[hook.match?.tool ?? "*"] : undefined;
      ops.push({ kind: "mergeJson", module, target: ".claude/settings.json",
                 path: ["hooks", EVENT_NAMES[hook.event]],
                 value: { ...(matcher ? { matcher } : {}), hooks: [{ type: "command", command }] },
                 match: { commandContains: script } });
    }
  }

  for (const [name, server] of Object.entries(def.contributes.mcpServers)) {
    ops.push({ kind: "mergeJson", module, target: scope === "project" ? ".mcp.json" : ".claude.json",
               path: ["mcpServers", name], value: server });
  }

  if (def.contributes.instructions.length > 0) {
    const content = def.contributes.instructions
      .map((file) => renderTemplate(def.files[file]!, vars, `${module}/${file}`).trim())
      .join("\n\n");
    ops.push({ kind: "markedBlock", module, target: scope === "project" ? "CLAUDE.md" : ".claude/CLAUDE.md",
               id: module, content });
  }

  if (scope === "project") {
    for (const scaffold of def.contributes.scaffold) {
      for (const file of under(def, scaffold.from)) {
        ops.push({ kind: "scaffoldOnce", module, target: `${scaffold.to}/${file.slice(scaffold.from.length + 1)}`,
                   content: renderTemplate(def.files[file]!, vars, `${module}/${file}`) });
      }
    }
  }
  return ops;
}

export const claudeCodeAdapter: HarnessAdapter = {
  id: "claude-code",
  capabilities: () => [...CAPABILITIES],
  allowedPrefixes: (scope) => (scope === "project" ? [""] : [".claude/", ".claude.json"]),
  translate,
};
```

- [ ] **Step 5: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/adapters test/claude-code-adapter.test.ts
git commit -m "feat: adapter interface and Claude Code adapter"
```

---

### Task 9: Planner — capabilities, config resolution, install/update/remove plans

**Files:**
- Create: `src/planner.ts`
- Test: `test/planner.test.ts`

**Interfaces:**
- Consumes: `HarnessAdapter`, `AdapterEnv`; `configValueProblem` from `src/schema.ts`; `fromPointer`, `toPointer`; types; `KitError`.
- Produces:
  - `impliedCapabilities(def: ModuleManifest): Capability[]` — what the module's contributions need, whether or not it declares them.
  - `supportStatus(def: ModuleManifest, adapter: HarnessAdapter): { status: "supported" | "degraded" | "unsupported"; missing: Capability[] }` — `missing` lists required capabilities when unsupported, optional ones when degraded.
  - `resolveConfig(def: ModuleManifest, provided: Record<string, unknown>): Record<string, unknown>` — applies defaults, validates types, rejects unknown keys.
  - `interface Selection { def: ModuleDef; config: Record<string, unknown> }`
  - `planModule(selection: Selection, scope: Scope, adapter: HarnessAdapter, env: AdapterEnv, lock: Lockfile): Operation[]` — install *and* update: the adapter's operations, with `expectedHash` filled in from the lock, preceded by removals of anything the previous install owned that the new one no longer produces.
  - `planRemove(names: string[], lock: Lockfile): Operation[]` — removes all the named modules in one plan. A file is kept only if a module *outside* `names` also owns it (the shared runtime shim); a file shared by two removed modules is deleted once.

- [ ] **Step 1: Write the failing test**

`test/planner.test.ts`:
```ts
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { getAdapter, type HarnessAdapter } from "../src/adapters/adapter.js";
import { loadCatalog, resolveModule } from "../src/catalog/load.js";
import { emptyLock } from "../src/lockfile.js";
import { impliedCapabilities, planModule, planRemove, resolveConfig, supportStatus } from "../src/planner.js";
import type { Lockfile, ModuleLock } from "../src/types.js";

const catalogs = [loadCatalog(join(import.meta.dirname, "fixtures/catalog"))];
const alpha = resolveModule(catalogs, "alpha");
const beta = resolveModule(catalogs, "beta");
const claude = getAdapter("claude-code");
const env = { home: "/home/u" };
const limited: HarnessAdapter = { ...claude, id: "limited", capabilities: () => ["skills", "instructions", "mcp"] };

const moduleLock = (owned: Partial<ModuleLock["owned"]>): ModuleLock => ({
  catalog: "public", version: "0.9.0", config: {}, scaffolded: [],
  owned: { files: [], json: [], blocks: [], ...owned },
});

describe("capabilities", () => {
  it("derives capabilities from contributions", () => {
    expect(impliedCapabilities(alpha).sort()).toEqual(
      ["instructions", "mcp", "pre-tool-hook", "session-hook", "skills"]);
    expect(impliedCapabilities(beta).sort()).toEqual(["pre-tool-hook", "subagent-intercept"]);
  });

  it("classifies support", () => {
    expect(supportStatus(alpha, claude)).toEqual({ status: "supported", missing: [] });
    expect(supportStatus(alpha, limited)).toEqual({ status: "unsupported", missing: ["pre-tool-hook", "session-hook"] });
    const wantsStatusline = { ...alpha,
      requires: { capabilities: [], optional: ["statusline" as const], env: [] },
      contributes: { ...alpha.contributes, hooks: [] } };
    expect(supportStatus(wantsStatusline, limited)).toEqual({ status: "degraded", missing: ["statusline"] });
  });

  it("refuses an unsupported module before producing any operation", () => {
    expect(() => planModule({ def: beta, config: {} }, "user", limited, env, emptyLock()))
      .toThrowError(/module "beta" needs capabilities that limited lacks: pre-tool-hook, subagent-intercept/);
  });

  it("refuses a scope the module does not support", () => {
    expect(() => planModule({ def: alpha, config: {} }, "user", claude, env, emptyLock()))
      .toThrowError(/module "alpha" does not support user scope \(supports: project\)/);
  });
});

describe("resolveConfig", () => {
  it("applies defaults and keeps provided values", () => {
    expect(resolveConfig(alpha, { greeting: "yo" })).toEqual({ greeting: "yo", areas: ["api"] });
  });

  it("rejects wrong types, unknown keys and missing values", () => {
    expect(() => resolveConfig(alpha, { greeting: 5 })).toThrowError(/alpha: config "greeting" must be a string/);
    expect(() => resolveConfig(alpha, { nope: 1 })).toThrowError(/alpha: unknown config "nope"/);
    expect(() => resolveConfig(beta, { mode: "loud" })).toThrowError(/one of warn, block/);
    const noDefault = { ...alpha, config: { token: { type: "string" as const } } };
    expect(() => resolveConfig(noDefault, {})).toThrowError(/alpha: config "token" has no value/);
  });
});

describe("planModule", () => {
  it("is the adapter's operations on a fresh install", () => {
    const ops = planModule({ def: alpha, config: { greeting: "hi" } }, "project", claude, env, emptyLock());
    expect(ops).toEqual(claude.translate(alpha, { greeting: "hi", areas: ["api"] }, "project", env));
  });

  it("on update, carries expected hashes and removes what the new version no longer produces", () => {
    const lock: Lockfile = { ...emptyLock(), modules: { alpha: moduleLock({
      files: [{ path: ".claude/skills/alpha-skill/SKILL.md", hash: "sha256:old" },
              { path: ".claude/kit/hooks/alpha/retired.mjs", hash: "sha256:gone" }],
      json: [{ file: ".claude/settings.json", pointer: "/hooks/Stop", match: { commandContains: "kit/hooks/alpha/retired.mjs" } },
             { file: ".mcp.json", pointer: "/mcpServers/alpha-mcp" }],
      blocks: [{ file: "CLAUDE.md", id: "alpha" }, { file: "AGENTS.md", id: "alpha" }],
    }) } };
    const ops = planModule({ def: alpha, config: {} }, "project", claude, env, lock);
    expect(ops.slice(0, 3)).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/hooks/alpha/retired.mjs", expectedHash: "sha256:gone" },
      { kind: "removeJson", module: "alpha", target: ".claude/settings.json", path: ["hooks", "Stop"],
        match: { commandContains: "kit/hooks/alpha/retired.mjs" } },
      { kind: "removeBlock", module: "alpha", target: "AGENTS.md", id: "alpha" },
    ]);
    const skill = ops.find((o) => o.kind === "writeOwned" && o.target.endsWith("SKILL.md"));
    expect(skill).toMatchObject({ expectedHash: "sha256:old" });
  });

  it("finds the expected hash of a shared file owned by another module", () => {
    const lock: Lockfile = { ...emptyLock(), modules: { beta: moduleLock({
      files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }] }) } };
    const ops = planModule({ def: alpha, config: {} }, "project", claude, env, lock);
    expect(ops.find((o) => o.target === ".claude/kit/runtime.mjs")).toMatchObject({ expectedHash: "sha256:rt" });
  });
});

describe("planRemove", () => {
  const lock: Lockfile = { ...emptyLock(), modules: {
    alpha: moduleLock({
      files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }, { path: ".claude/kit/hooks/alpha/check.mjs", hash: "sha256:c" }],
      json: [{ file: ".mcp.json", pointer: "/mcpServers/alpha-mcp" }],
      blocks: [{ file: "CLAUDE.md", id: "alpha" }] }),
    beta: moduleLock({ files: [{ path: ".claude/kit/runtime.mjs", hash: "sha256:rt" }] }),
  } };

  it("inverts what the lock records, keeping files other modules still own", () => {
    expect(planRemove(["alpha"], lock)).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/hooks/alpha/check.mjs", expectedHash: "sha256:c" },
      { kind: "removeJson", module: "alpha", target: ".mcp.json", path: ["mcpServers", "alpha-mcp"] },
      { kind: "removeBlock", module: "alpha", target: "CLAUDE.md", id: "alpha" },
    ]);
  });

  it("deletes the shared file when the last owner goes", () => {
    const onlyBeta: Lockfile = { ...lock, modules: { beta: lock.modules.beta! } };
    expect(planRemove(["beta"], onlyBeta)).toEqual([
      { kind: "deleteOwned", module: "beta", target: ".claude/kit/runtime.mjs", expectedHash: "sha256:rt" }]);
  });

  it("deletes a shared file exactly once when all its owners are removed together", () => {
    const runtimeDeletes = planRemove(["alpha", "beta"], lock)
      .filter((o) => o.kind === "deleteOwned" && o.target === ".claude/kit/runtime.mjs");
    expect(runtimeDeletes).toEqual([
      { kind: "deleteOwned", module: "alpha", target: ".claude/kit/runtime.mjs", expectedHash: "sha256:rt" }]);
  });

  it("rejects a module that is not installed", () => {
    expect(() => planRemove(["nope"], lock)).toThrowError(/module "nope" is not installed/);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/planner.test.ts`
Expected: FAIL — cannot resolve `../src/planner.js`.

- [ ] **Step 3: Implement `src/planner.ts`**

```ts
import type { AdapterEnv, HarnessAdapter } from "./adapters/adapter.js";
import { KitError } from "./errors.js";
import { fromPointer, toPointer } from "./ops/json-merge.js";
import { configValueProblem } from "./schema.js";
import type {
  Capability, HookEvent, Lockfile, ModuleDef, ModuleManifest, Operation, OwnedJson, Scope,
} from "./types.js";

const EVENT_CAPABILITY: Record<HookEvent, Capability> = {
  "pre-tool-use": "pre-tool-hook", "post-tool-use": "post-tool-hook",
  "session-start": "session-hook", "stop": "session-hook",
  "user-prompt": "user-prompt-hook", "subagent-start": "subagent-intercept",
};

export function impliedCapabilities(def: ModuleManifest): Capability[] {
  const caps = new Set<Capability>();
  if (def.contributes.skills.length > 0) caps.add("skills");
  if (def.contributes.instructions.length > 0) caps.add("instructions");
  if (Object.keys(def.contributes.mcpServers).length > 0) caps.add("mcp");
  for (const hook of def.contributes.hooks) {
    caps.add(EVENT_CAPABILITY[hook.event]);
    if (hook.match?.tool === "subagent") caps.add("subagent-intercept");
  }
  return [...caps];
}

export function supportStatus(
  def: ModuleManifest, adapter: HarnessAdapter,
): { status: "supported" | "degraded" | "unsupported"; missing: Capability[] } {
  const available = new Set(adapter.capabilities());
  const lacking = (caps: Capability[]) => [...new Set(caps)].filter((c) => !available.has(c)).sort();
  const required = lacking([...def.requires.capabilities, ...impliedCapabilities(def)]);
  if (required.length > 0) return { status: "unsupported", missing: required };
  const optional = lacking(def.requires.optional);
  return optional.length > 0 ? { status: "degraded", missing: optional } : { status: "supported", missing: [] };
}

export function resolveConfig(def: ModuleManifest, provided: Record<string, unknown>): Record<string, unknown> {
  for (const key of Object.keys(provided)) {
    if (!(key in def.config)) throw new KitError(`${def.name}: unknown config "${key}"`);
  }
  const resolved: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(def.config)) {
    const value = provided[key] ?? field.default;
    if (value === undefined) throw new KitError(`${def.name}: config "${key}" has no value`);
    const problem = configValueProblem(key, field, value);
    if (problem) throw new KitError(`${def.name}: ${problem}`);
    resolved[key] = value;
  }
  return resolved;
}

export interface Selection { def: ModuleDef; config: Record<string, unknown> }

function ownedHash(lock: Lockfile, target: string): string | undefined {
  for (const entry of Object.values(lock.modules)) {
    const hit = entry.owned.files.find((f) => f.path === target);
    if (hit) return hit.hash;
  }
  return undefined;
}

const ownedByOthers = (lock: Lockfile, names: string[], target: string): boolean =>
  Object.entries(lock.modules).some(([other, entry]) =>
    !names.includes(other) && entry.owned.files.some((f) => f.path === target));

const jsonKey = (file: string, pointer: string, match?: { commandContains: string }): string =>
  `${file} ${pointer} ${match?.commandContains ?? ""}`;

const removeJsonOp = (module: string, entry: OwnedJson): Operation => ({
  kind: "removeJson", module, target: entry.file, path: fromPointer(entry.pointer),
  ...(entry.match ? { match: entry.match } : {}),
});

export function planModule(
  selection: Selection, scope: Scope, adapter: HarnessAdapter, env: AdapterEnv, lock: Lockfile,
): Operation[] {
  const { def } = selection;
  if (!def.scopes.includes(scope)) {
    throw new KitError(`module "${def.name}" does not support ${scope} scope (supports: ${def.scopes.join(", ")})`);
  }
  const support = supportStatus(def, adapter);
  if (support.status === "unsupported") {
    throw new KitError(`module "${def.name}" needs capabilities that ${adapter.id} lacks: ${support.missing.join(", ")}`);
  }

  const forward = adapter.translate(def, resolveConfig(def, selection.config), scope, env).map((op) => {
    if (op.kind !== "writeOwned") return op;
    const expectedHash = ownedHash(lock, op.target);
    return expectedHash === undefined ? op : { ...op, expectedHash };
  });

  const previous = lock.modules[def.name];
  if (!previous) return forward;

  const files = new Set(forward.filter((o) => o.kind === "writeOwned").map((o) => o.target));
  const json = new Set(forward.flatMap((o) => (o.kind === "mergeJson" ? [jsonKey(o.target, toPointer(o.path), o.match)] : [])));
  const blocks = new Set(forward.flatMap((o) => (o.kind === "markedBlock" ? [`${o.target} ${o.id}`] : [])));

  const stale: Operation[] = [];
  for (const f of previous.owned.files) {
    if (!files.has(f.path) && !ownedByOthers(lock, [def.name], f.path)) {
      stale.push({ kind: "deleteOwned", module: def.name, target: f.path, expectedHash: f.hash });
    }
  }
  for (const j of previous.owned.json) {
    if (!json.has(jsonKey(j.file, j.pointer, j.match))) stale.push(removeJsonOp(def.name, j));
  }
  for (const b of previous.owned.blocks) {
    if (!blocks.has(`${b.file} ${b.id}`)) stale.push({ kind: "removeBlock", module: def.name, target: b.file, id: b.id });
  }
  return [...stale, ...forward];
}

export function planRemove(names: string[], lock: Lockfile): Operation[] {
  const ops: Operation[] = [];
  const deleted = new Set<string>();
  for (const name of names) {
    const entry = lock.modules[name];
    if (!entry) throw new KitError(`module "${name}" is not installed`);
    for (const f of entry.owned.files) {
      if (deleted.has(f.path) || ownedByOthers(lock, names, f.path)) continue;
      deleted.add(f.path);
      ops.push({ kind: "deleteOwned", module: name, target: f.path, expectedHash: f.hash });
    }
    for (const j of entry.owned.json) ops.push(removeJsonOp(name, j));
    for (const b of entry.owned.blocks) ops.push({ kind: "removeBlock", module: name, target: b.file, id: b.id });
  }
  return ops;
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/planner.ts test/planner.test.ts
git commit -m "feat: planner for install, update and remove"
```

---

### Task 10: Git catalog sources and shared test helpers

**Files:**
- Create: `src/catalog/source.ts`
- Modify: `test/helpers.ts` (add git and snapshot helpers)
- Test: `test/catalog-source.test.ts`

**Interfaces:**
- Consumes: `CatalogSource`; `KitError`.
- Produces:
  - `interface FetchedCatalog { source: CatalogSource; dir: string; sha: string }` — `dir` already includes `source.subdir`.
  - `fetchCatalog(source: CatalogSource, cacheRoot: string, options?: { offline?: boolean; sha?: string }): FetchedCatalog` — clones into `<cacheRoot>/<hash of url+ref>`, or fetches if already cloned; checks out `options.sha` if given, else the tip of `source.ref` (branch, tag, or commit; default: the remote's default branch). `offline` skips all network access and requires a cached clone.
  - Test helpers: `FIXTURES: { public: string; company: string }`, `git(cwd: string, ...args: string[]): string`, `makeGitCatalog(fixtureDir: string): string` (copies a fixture into a temp dir and commits it on branch `main`), `commitAll(repo: string, message: string): string` (returns the new sha), `snapshotTree(root: string, exclude?: string[]): Record<string, string>` (relative path → content; always skips `.git`; `exclude` entries are relative path prefixes).

- [ ] **Step 1: Extend `test/helpers.ts`**

Replace the file with:
```ts
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const FIXTURES = {
  public: join(import.meta.dirname, "fixtures/catalog"),
  company: join(import.meta.dirname, "fixtures/company-catalog"),
};

/** A fresh temp directory, realpath'd (on macOS /tmp is a symlink). */
export function tempDir(prefix = "kit-"): string {
  return realpathSync(mkdtempSync(join(tmpdir(), prefix)));
}

export function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=kit-test", "-c", "user.email=kit@test.invalid", ...args],
    { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

export function commitAll(repo: string, message: string): string {
  git(repo, "add", "-A");
  git(repo, "commit", "--quiet", "-m", message);
  return git(repo, "rev-parse", "HEAD");
}

export function makeGitCatalog(fixtureDir: string): string {
  const repo = tempDir("kit-catalog-");
  cpSync(fixtureDir, repo, { recursive: true });
  git(repo, "init", "--quiet", "-b", "main");
  commitAll(repo, "initial catalog");
  return repo;
}

export function snapshotTree(root: string, exclude: string[] = []): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (rel === ".git" || exclude.some((e) => rel === e || rel.startsWith(e + "/"))) continue;
      if (entry.isDirectory()) walk(join(dir, entry.name), rel);
      else out[rel] = readFileSync(join(dir, entry.name), "utf8");
    }
  };
  walk(root, "");
  return out;
}
```

- [ ] **Step 2: Write the failing test**

`test/catalog-source.test.ts`:
```ts
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fetchCatalog } from "../src/catalog/source.js";
import { commitAll, FIXTURES, git, makeGitCatalog, tempDir } from "./helpers.js";

describe("fetchCatalog", () => {
  it("clones, reports the sha, then follows new commits", () => {
    const repo = makeGitCatalog(FIXTURES.public);
    const cache = tempDir("kit-cache-");
    const first = fetchCatalog({ url: repo }, cache);
    expect(first.sha).toBe(git(repo, "rev-parse", "HEAD"));
    expect(existsSync(join(first.dir, "catalog.json"))).toBe(true);

    writeFileSync(join(repo, "NEW.md"), "new");
    const newSha = commitAll(repo, "second");
    const second = fetchCatalog({ url: repo }, cache);
    expect(second.sha).toBe(newSha);
    expect(second.dir).toBe(first.dir);
    expect(existsSync(join(second.dir, "NEW.md"))).toBe(true);
  });

  it("checks out a pinned sha, and works offline from the cache", () => {
    const repo = makeGitCatalog(FIXTURES.public);
    const cache = tempDir("kit-cache-");
    const pinned = fetchCatalog({ url: repo }, cache).sha;
    writeFileSync(join(repo, "NEW.md"), "new");
    commitAll(repo, "second");
    fetchCatalog({ url: repo }, cache);

    const back = fetchCatalog({ url: repo }, cache, { sha: pinned, offline: true });
    expect(back.sha).toBe(pinned);
    expect(existsSync(join(back.dir, "NEW.md"))).toBe(false);
  });

  it("supports refs (branch and tag) and subdirectories", () => {
    const repo = tempDir("kit-mono-");
    git(repo, "init", "--quiet", "-b", "main");
    writeFileSync(join(repo, "README.md"), "engine");
    commitAll(repo, "engine");
    git(repo, "tag", "v1");
    git(repo, "checkout", "--quiet", "-b", "next");
    writeFileSync(join(repo, "NEXT.md"), "next");
    const nextSha = commitAll(repo, "next");
    const cache = tempDir("kit-cache-");
    expect(fetchCatalog({ url: repo, ref: "next" }, cache).sha).toBe(nextSha);
    expect(existsSync(join(fetchCatalog({ url: repo, ref: "v1" }, cache).dir, "NEXT.md"))).toBe(false);
    expect(() => fetchCatalog({ url: repo, ref: "main", subdir: "catalog" }, cache))
      .toThrowError(/subdirectory "catalog" not found/);
  });

  it("explains failures", () => {
    const cache = tempDir("kit-cache-");
    expect(() => fetchCatalog({ url: join(cache, "does-not-exist") }, cache)).toThrowError(/git clone failed/);
    const repo = makeGitCatalog(FIXTURES.public);
    expect(() => fetchCatalog({ url: repo }, cache, { offline: true })).toThrowError(/not cached.*--offline/);
    expect(() => fetchCatalog({ url: repo, ref: "nope" }, cache)).toThrowError(/ref "nope" not found/);
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npx vitest run test/catalog-source.test.ts`
Expected: FAIL — cannot resolve `../src/catalog/source.js`.

- [ ] **Step 4: Implement `src/catalog/source.ts`**

```ts
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { KitError } from "../errors.js";
import type { CatalogSource } from "../types.js";

export interface FetchedCatalog { source: CatalogSource; dir: string; sha: string }

function git(args: string[], cwd?: string): string {
  try {
    return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  } catch (err) {
    const e = err as { stderr?: string; message: string };
    throw new KitError(`git ${args[0]} failed: ${(e.stderr || e.message).trim()}`);
  }
}

function resolveRef(clone: string, source: CatalogSource): string {
  const candidates = source.ref ? [`origin/${source.ref}`, source.ref] : ["origin/HEAD"];
  for (const candidate of candidates) {
    try {
      return git(["rev-parse", "--verify", "--quiet", `${candidate}^{commit}`], clone);
    } catch {
      // try the next spelling
    }
  }
  throw new KitError(`ref "${source.ref ?? "HEAD"}" not found in ${source.url}`);
}

export function fetchCatalog(
  source: CatalogSource, cacheRoot: string, options: { offline?: boolean; sha?: string } = {},
): FetchedCatalog {
  const key = createHash("sha1").update(`${source.url}\n${source.ref ?? ""}`).digest("hex").slice(0, 16);
  const clone = join(cacheRoot, key);
  const cached = existsSync(join(clone, ".git"));

  if (options.offline) {
    if (!cached) throw new KitError(`catalog ${source.url} is not cached; run once without --offline`);
  } else if (!cached) {
    mkdirSync(cacheRoot, { recursive: true });
    git(["clone", "--quiet", "--", source.url, clone]);
  } else {
    git(["fetch", "--quiet", "--tags", "--prune", "origin"], clone);
  }

  git(["checkout", "--quiet", "--detach", options.sha ?? resolveRef(clone, source)], clone);
  const sha = git(["rev-parse", "HEAD"], clone);
  const dir = source.subdir ? join(clone, source.subdir) : clone;
  if (!existsSync(dir)) throw new KitError(`subdirectory "${source.subdir}" not found in ${source.url}`);
  return { source, dir, sha };
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/catalog/source.ts test/helpers.ts test/catalog-source.test.ts
git commit -m "feat: git catalog sources with cache, pinning and offline mode"
```

---
### Task 11: CLI skeleton, prompts, `validate` and `catalog` commands, the example module

**Files:**
- Create: `src/env.ts`, `src/prompts.ts`, `src/cli.ts`, `src/bin.ts`, `src/commands/validate.ts`, `src/commands/catalog.ts`
- Create: `catalog/catalog.json`, `catalog/profiles/example.json`, `catalog/modules/kit-example/` (files in Step 1)
- Create: `test/cli-helpers.ts`
- Test: `test/cli-basic.test.ts`

**Interfaces:**
- Consumes: `loadCatalog`, `fetchCatalog`, `readUserConfig`, `writeUserConfig`, `sourceKey`, `catalogCacheDir`, `getAdapter`, `supportStatus`, `resolveConfig`, `KitError`.
- Produces:
  - `src/env.ts`: `interface Flags { yes: boolean; dryRun: boolean; offline: boolean; harness: string; scope?: Scope; profile?: string; ref?: string; subdir?: string; catalog: string[] }`, `interface Env { cwd: string; home: string; out: (line: string) => void; prompter: Prompter; flags: Flags }`, `type Command = (args: string[], env: Env) => Promise<number>` (returns the exit code).
  - `src/prompts.ts`: `interface Choice<T> { value: T; label: string; hint?: string }`; `interface Prompter { select<T>(message: string, choices: Choice<T>[], initial?: T): Promise<T>; multiselect<T>(message: string, choices: Choice<T>[], initial: T[]): Promise<T[]>; text(message: string, initial?: string, validate?: (value: string) => string | undefined): Promise<string>; confirm(message: string, initial?: boolean): Promise<boolean> }`; `clackPrompter: Prompter`; `promptConfig(def: ModuleManifest, current: Record<string, unknown>, prompter: Prompter): Promise<Record<string, unknown>>`.
  - `src/cli.ts`: `main(argv: string[], overrides?: Partial<Omit<Env, "flags">>): Promise<number>`; `USAGE: string`. Later tasks register commands by adding an import and one entry to the `COMMANDS` object.
  - `test/cli-helpers.ts`: `interface Answers { select?: unknown[]; multiselect?: unknown[][]; text?: string[]; confirm?: boolean[] }`; `fakePrompter(answers: Answers): Prompter & { asked: string[] }` (answers are consumed in order; when a queue is empty the prompt's initial value is returned); `runKit(args: string[], ctx: { cwd: string; home: string; answers?: Answers }): Promise<{ code: number; output: string; asked: string[] }>`; `interface Workspace { home: string; project: string; publicRepo: string }`; `makeWorkspace(): Workspace` (temp home, a `git init`-ed temp project, the public fixture as a git catalog already registered in the user config).

- [ ] **Step 1: Create the public catalog and its example module**

`catalog/catalog.json`:
```json
{ "name": "public", "modules": ["modules/kit-example"], "profiles": ["profiles/example.json"] }
```

`catalog/profiles/example.json`:
```json
{
  "name": "example",
  "description": "Installs the example module; use it to check that the kit works in your harness",
  "modules": { "kit-example": { "scope": "project" } }
}
```

`catalog/modules/kit-example/module.json`:
```json
{
  "name": "kit-example",
  "version": "0.1.0",
  "description": "Reference module: a skill, two hooks, an instruction fragment and a scaffold",
  "scopes": ["project"],
  "config": {
    "greeting": { "type": "string", "default": "hello", "prompt": "Greeting shown at session start" }
  },
  "contributes": {
    "skills": ["skills/kit-example"],
    "hooks": [
      { "event": "session-start", "run": "hooks/announce.mjs" },
      { "event": "pre-tool-use", "match": { "tool": "shell" }, "run": "hooks/guard.mjs" }
    ],
    "instructions": ["instructions/kit-example.md"],
    "scaffold": [{ "from": "templates/docs", "to": "docs/kit-example" }]
  }
}
```

`catalog/modules/kit-example/skills/kit-example/SKILL.md`:
```markdown
---
name: kit-example
description: Use when the user asks whether the harness kit is installed or working.
---

# Kit example

Reply that the harness kit example module is installed, and mention that shell
commands containing `kit-example-deny-me` are blocked by its hook.
```

`catalog/modules/kit-example/hooks/announce.mjs`:
```js
import { run } from "../../runtime.mjs";

run(({ config, warn }) => warn(`kit-example is active: ${config.greeting}`));
```

`catalog/modules/kit-example/hooks/guard.mjs`:
```js
import { run } from "../../runtime.mjs";

run(({ tool, allow, deny }) => {
  const command = String(tool.input?.command ?? "");
  return command.includes("kit-example-deny-me")
    ? deny("kit-example blocked this command (it contains kit-example-deny-me)")
    : allow();
});
```

`catalog/modules/kit-example/instructions/kit-example.md`:
```markdown
## Harness kit example

The kit-example module is installed (greeting: "{{config.greeting}}").
```

`catalog/modules/kit-example/templates/docs/README.md`:
```markdown
# kit-example

Scaffolded once by {{module.name}} {{module.version}}. This file is yours now;
the kit will never overwrite or delete it.
```

`catalog/modules/kit-example/README.md`:
```markdown
# kit-example

Reference module for catalog authors. Copy this folder to start a new module.
```

- [ ] **Step 2: Create `test/cli-helpers.ts`**

```ts
import { join } from "node:path";
import { main } from "../src/cli.js";
import type { Choice, Prompter } from "../src/prompts.js";
import { writeUserConfig } from "../src/userconfig.js";
import { FIXTURES, git, makeGitCatalog, tempDir } from "./helpers.js";

export interface Answers { select?: unknown[]; multiselect?: unknown[][]; text?: string[]; confirm?: boolean[] }

export function fakePrompter(answers: Answers): Prompter & { asked: string[] } {
  const queues = {
    select: [...(answers.select ?? [])], multiselect: [...(answers.multiselect ?? [])],
    text: [...(answers.text ?? [])], confirm: [...(answers.confirm ?? [])],
  };
  const asked: string[] = [];
  return {
    asked,
    async select<T>(message: string, choices: Choice<T>[], initial?: T) {
      asked.push(message);
      return (queues.select.length > 0 ? queues.select.shift() : initial ?? choices[0]!.value) as T;
    },
    async multiselect<T>(message: string, _choices: Choice<T>[], initial: T[]) {
      asked.push(message);
      return (queues.multiselect.length > 0 ? queues.multiselect.shift() : initial) as T[];
    },
    async text(message: string, initial?: string) {
      asked.push(message);
      return queues.text.length > 0 ? queues.text.shift()! : initial ?? "";
    },
    async confirm(message: string, initial?: boolean) {
      asked.push(message);
      return queues.confirm.length > 0 ? queues.confirm.shift()! : initial ?? true;
    },
  };
}

export async function runKit(
  args: string[], ctx: { cwd: string; home: string; answers?: Answers },
): Promise<{ code: number; output: string; asked: string[] }> {
  const lines: string[] = [];
  const prompter = fakePrompter(ctx.answers ?? {});
  const code = await main(args, { cwd: ctx.cwd, home: ctx.home, out: (line) => lines.push(line), prompter });
  return { code, output: lines.join("\n"), asked: prompter.asked };
}

export interface Workspace { home: string; project: string; publicRepo: string }

export function makeWorkspace(): Workspace {
  const home = tempDir("kit-home-");
  const project = tempDir("kit-project-");
  git(project, "init", "--quiet", "-b", "main");
  const publicRepo = makeGitCatalog(FIXTURES.public);
  writeUserConfig(home, { catalogs: [{ url: publicRepo }] });
  return { home, project, publicRepo };
}

export const inProject = (ws: Workspace, ...parts: string[]): string => join(ws.project, ...parts);
export const inHome = (ws: Workspace, ...parts: string[]): string => join(ws.home, ...parts);
```

- [ ] **Step 3: Write the failing test**

`test/cli-basic.test.ts`:
```ts
import { cpSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readUserConfig } from "../src/userconfig.js";
import { runKit } from "./cli-helpers.js";
import { FIXTURES, makeGitCatalog, tempDir } from "./helpers.js";

const REPO_CATALOG = join(import.meta.dirname, "../catalog");
const ctx = () => ({ cwd: tempDir("kit-cwd-"), home: tempDir("kit-home-") });

describe("kit cli basics", () => {
  it("prints usage with --help and with no command", async () => {
    expect((await runKit(["--help"], ctx())).output).toContain("Usage: kit <command>");
    expect(await runKit([], ctx())).toMatchObject({ code: 0 });
  });

  it("fails cleanly on unknown commands, flags and scopes", async () => {
    expect(await runKit(["frobnicate"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining('unknown command "frobnicate"') });
    expect(await runKit(["validate", "--nope"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining("error:") });
    expect(await runKit(["validate", "x", "--scope", "galaxy"], ctx())).toMatchObject({ code: 1, output: expect.stringContaining("--scope must be project or user") });
  });
});

describe("kit validate", () => {
  it("accepts the fixture catalogs and the repo's public catalog", async () => {
    const r = await runKit(["validate", FIXTURES.public], ctx());
    expect(r.code).toBe(0);
    expect(r.output).toContain('catalog "public"');
    expect(r.output).toMatch(/ok\s+alpha@1\.0\.0 \(supported on claude-code\)/);
    expect((await runKit(["validate", REPO_CATALOG], ctx())).code).toBe(0);
  });

  it("notes profile entries that come from another catalog", async () => {
    const r = await runKit(["validate", FIXTURES.company], ctx());
    expect(r.code).toBe(0);
    expect(r.output).toContain('profile industrial: "alpha" is expected from another catalog');
  });

  it("fails on invalid modules and on bad profile config", async () => {
    const dir = tempDir("kit-bad-");
    cpSync(FIXTURES.public, dir, { recursive: true });
    const manifest = join(dir, "modules/beta/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace("hooks/guard.mjs", "hooks/missing.mjs"));
    const profile = join(dir, "profiles/dev.json");
    writeFileSync(profile, readFileSync(profile, "utf8").replace('"hi dev"', "42"));
    const r = await runKit(["validate", dir], ctx());
    expect(r.code).toBe(1);
    expect(r.output).toMatch(/INVALID\s+beta/);
    expect(r.output).toContain("missing hook script hooks/missing.mjs");
    expect(r.output).toContain('profile dev: alpha: config "greeting" must be a string');
  });
});

describe("kit catalog", () => {
  it("adds, lists and removes catalog sources", async () => {
    const c = ctx();
    const repo = makeGitCatalog(FIXTURES.public);
    const added = await runKit(["catalog", "add", repo], c);
    expect(added).toMatchObject({ code: 0, output: expect.stringContaining('added catalog "public" (2 modules, 1 profiles)') });
    expect(readUserConfig(c.home).catalogs).toEqual([{ url: repo }]);
    await runKit(["catalog", "add", repo, "--ref", "main"], c); // same source: replaced, not duplicated
    expect(readUserConfig(c.home).catalogs).toEqual([{ url: repo, ref: "main" }]);
    expect((await runKit(["catalog", "list"], c)).output).toContain(repo);
    expect((await runKit(["catalog", "remove", repo], c)).code).toBe(0);
    expect(readUserConfig(c.home).catalogs).toEqual([]);
    expect((await runKit(["catalog", "remove", repo], c)).code).toBe(1);
  });

  it("does not save a source that is not a catalog", async () => {
    const c = ctx();
    const r = await runKit(["catalog", "add", join(c.cwd, "nowhere")], c);
    expect(r.code).toBe(1);
    expect(readUserConfig(c.home).catalogs).toEqual([]);
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npx vitest run test/cli-basic.test.ts`
Expected: FAIL — cannot resolve `../src/cli.js`.

- [ ] **Step 5: Implement `src/env.ts` and `src/prompts.ts`**

`src/env.ts`:
```ts
import type { Prompter } from "./prompts.js";
import type { Scope } from "./types.js";

export interface Flags {
  yes: boolean;
  dryRun: boolean;
  offline: boolean;
  harness: string;
  scope?: Scope;
  profile?: string;
  ref?: string;
  subdir?: string;
  catalog: string[];
}

export interface Env {
  cwd: string;
  home: string;
  out: (line: string) => void;
  prompter: Prompter;
  flags: Flags;
}

/** Returns the process exit code. */
export type Command = (args: string[], env: Env) => Promise<number>;
```

`src/prompts.ts`:
```ts
import * as clack from "@clack/prompts";
import { KitError } from "./errors.js";
import type { ModuleManifest } from "./types.js";

export interface Choice<T> { value: T; label: string; hint?: string }

export interface Prompter {
  select<T>(message: string, choices: Choice<T>[], initial?: T): Promise<T>;
  multiselect<T>(message: string, choices: Choice<T>[], initial: T[]): Promise<T[]>;
  text(message: string, initial?: string, validate?: (value: string) => string | undefined): Promise<string>;
  confirm(message: string, initial?: boolean): Promise<boolean>;
}

function unwrap<T>(value: T | symbol): T {
  if (clack.isCancel(value)) throw new KitError("cancelled");
  return value as T;
}

// clack's option types are conditional on the value type; the casts keep our interface simple.
export const clackPrompter: Prompter = {
  async select<T>(message: string, choices: Choice<T>[], initial?: T) {
    return unwrap(await clack.select({ message, options: choices as never, initialValue: initial as never })) as T;
  },
  async multiselect<T>(message: string, choices: Choice<T>[], initial: T[]) {
    return unwrap(await clack.multiselect({
      message, options: choices as never, initialValues: initial as never, required: false })) as T[];
  },
  async text(message, initial, validate) {
    return unwrap(await clack.text({ message, initialValue: initial, validate: validate as never }));
  },
  async confirm(message, initial) {
    return unwrap(await clack.confirm({ message, initialValue: initial ?? true }));
  },
};

/** Ask every config question of a module, starting from `current` values, then manifest defaults. */
export async function promptConfig(
  def: ModuleManifest, current: Record<string, unknown>, prompter: Prompter,
): Promise<Record<string, unknown>> {
  const result: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(def.config)) {
    const message = `${def.name} › ${field.prompt ?? key}`;
    const start = current[key] ?? field.default;
    switch (field.type) {
      case "boolean":
        result[key] = await prompter.confirm(message, typeof start === "boolean" ? start : false);
        break;
      case "enum":
        result[key] = await prompter.select(message, (field.values ?? []).map((v) => ({ value: v, label: v })),
          typeof start === "string" ? start : undefined);
        break;
      case "number": {
        const answer = await prompter.text(message, start === undefined ? "" : String(start),
          (v) => (v.trim() !== "" && Number.isFinite(Number(v)) ? undefined : "Enter a number"));
        result[key] = Number(answer);
        break;
      }
      case "string[]": {
        const answer = await prompter.text(`${message} (comma-separated)`, Array.isArray(start) ? start.join(", ") : "");
        result[key] = answer.split(",").map((s) => s.trim()).filter((s) => s !== "");
        break;
      }
      case "string":
        result[key] = await prompter.text(message, typeof start === "string" ? start : "");
        break;
    }
  }
  return result;
}
```

- [ ] **Step 6: Implement the two commands**

`src/commands/validate.ts`:
```ts
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
```

`src/commands/catalog.ts`:
```ts
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
```

- [ ] **Step 7: Implement `src/cli.ts` and `src/bin.ts`**

`src/cli.ts`:
```ts
import { homedir } from "node:os";
import { parseArgs } from "node:util";
import { catalogCommand } from "./commands/catalog.js";
import { validateCommand } from "./commands/validate.js";
import type { Command, Env } from "./env.js";
import { KitError } from "./errors.js";
import { clackPrompter } from "./prompts.js";
import { SCOPES, type Scope } from "./types.js";

const COMMANDS: Record<string, Command> = {
  catalog: catalogCommand,
  validate: validateCommand,
};

export const USAGE = `Usage: kit <command> [options]

Commands:
  init [--profile P]           choose a profile and modules, then install them
  add <module…>                install modules
  remove <module…>             uninstall modules
  update [module…]             move installed modules to the latest catalog version
  config <module>              change a module's settings
  list                         show catalog modules and what is installed
  status                       report drift, outdated modules and missing env vars
  catalog list|add|remove      manage catalog sources
  validate <catalog-path>      lint a catalog (for catalog CI)

Options:
  --scope project|user   where to install or look (default: the module's first scope)
  --yes, -y              no prompts; keep your version of any file you edited
  --dry-run              show the plan, write nothing
  --offline              use cached catalogs only
  --catalog <git-url>    use an extra catalog for this run (repeatable)
  --ref R, --subdir D    branch/tag/commit and subdirectory for catalog add / --catalog
  --harness H            target harness (default: claude-code)
  --help, -h`;

export async function main(argv: string[], overrides: Partial<Omit<Env, "flags">> = {}): Promise<number> {
  const out = overrides.out ?? ((line: string) => console.log(line));
  try {
    const { values, positionals } = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        yes: { type: "boolean", short: "y" },
        "dry-run": { type: "boolean" },
        offline: { type: "boolean" },
        help: { type: "boolean", short: "h" },
        scope: { type: "string" },
        profile: { type: "string" },
        harness: { type: "string" },
        ref: { type: "string" },
        subdir: { type: "string" },
        catalog: { type: "string", multiple: true },
      },
    });
    const [name, ...args] = positionals;
    if (values.help || name === undefined) {
      out(USAGE);
      return 0;
    }
    const command = COMMANDS[name];
    if (!command) throw new KitError(`unknown command "${name}"\n\n${USAGE}`);
    if (values.scope !== undefined && !(SCOPES as readonly string[]).includes(values.scope)) {
      throw new KitError("--scope must be project or user");
    }
    const env: Env = {
      cwd: overrides.cwd ?? process.cwd(),
      home: overrides.home ?? process.env.HARNESS_KIT_HOME ?? homedir(),
      out,
      prompter: overrides.prompter ?? clackPrompter,
      flags: {
        yes: values.yes ?? false,
        dryRun: values["dry-run"] ?? false,
        offline: values.offline ?? false,
        harness: values.harness ?? "claude-code",
        scope: values.scope as Scope | undefined,
        profile: values.profile,
        ref: values.ref,
        subdir: values.subdir,
        catalog: values.catalog ?? [],
      },
    };
    return await command(args, env);
  } catch (err) {
    const parseError = err instanceof TypeError && String((err as { code?: string }).code).startsWith("ERR_PARSE_ARGS");
    if (err instanceof KitError || parseError) {
      out(`error: ${(err as Error).message}`);
      return 1;
    }
    throw err;
  }
}
```

`src/bin.ts`:
```ts
#!/usr/bin/env node
import { main } from "./cli.js";

process.exitCode = await main(process.argv.slice(2));
```

- [ ] **Step 8: Run tests, typecheck, and build**

Run: `npm test && npm run typecheck && npm run build && node dist/bin.js validate catalog`
Expected: tests PASS; the last command prints `catalog "public"` and `ok       kit-example@0.1.0 (supported on claude-code)` and exits 0.

- [ ] **Step 9: Commit**

```bash
git add src/env.ts src/prompts.ts src/cli.ts src/bin.ts src/commands catalog test/cli-helpers.ts test/cli-basic.test.ts
git commit -m "feat: CLI skeleton, validate and catalog commands, example module"
```

---

### Task 12: Install pipeline, `init` and `add`

**Files:**
- Create: `src/diff.ts`, `src/pipeline.ts`, `src/commands/init.ts`, `src/commands/add.ts`
- Modify: `src/cli.ts` (register two commands)
- Test: `test/diff.test.ts`, `test/install.test.ts`

**Interfaces:**
- Consumes: everything from Tasks 1–11.
- Produces:
  - `lineDiff(before: string, after: string): string[]` — changed lines only, prefixed `- ` or `+ `, in file order.
  - `interface LoadedCatalogs { catalogs: Catalog[]; locks: Record<string, CatalogLock> }` (`locks` is keyed by catalog name)
  - `loadCatalogs(env: Env, options: { pin: boolean }): LoadedCatalogs` — sources, in priority order: project lock, user lock, user config, `--catalog` flags; de-duplicated by `sourceKey`. With `pin: true`, a catalog recorded in a lock is checked out at its locked sha, so `init`/`add`/`config` never upgrade other modules by surprise; `update` passes `pin: false`. Prints a warning per invalid module.
  - `loadCatalogsWithFallback(env: Env): LoadedCatalogs | null` — unpinned; on fetch failure warns and retries offline; `null` if nothing is available. For `list` and `status`.
  - `interface ScopeContext { scope: Scope; adapter: HarnessAdapter; scopeRoot: ScopeRoot; lockFile: string; backupDir: string; lock: Lockfile }`
  - `openScope(scope: Scope, env: Env): ScopeContext`
  - `findInstalled(name: string, env: Env): ScopeContext` — the scope where `name` is installed; honours `--scope`; throws if not installed, or installed at both scopes without `--scope`.
  - `applyPlan(ctx: ScopeContext, ops: Operation[], env: Env): Promise<Staged | null>` — stages, prints the plan (including a line diff of every changed hook script and runtime shim), asks for confirmation unless `--yes`, commits. Returns `null` when nothing was committed (`--dry-run` or declined).
  - `interface InstallItem { def: ModuleDef; config: Record<string, unknown>; scope: Scope }`
  - `installModules(items: InstallItem[], loaded: LoadedCatalogs, env: Env, profile?: string): Promise<void>` — plans, applies and records each scope's items in its lockfile. Used for install, update and reconfigure alike.

- [ ] **Step 1: Write the failing diff test**

`test/diff.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { lineDiff } from "../src/diff.js";

describe("lineDiff", () => {
  it("reports only changed lines, in order", () => {
    expect(lineDiff("a\nb\nc\n", "a\nB\nc\nd\n")).toEqual(["- b", "+ B", "+ d"]);
  });
  it("is empty for identical input", () => {
    expect(lineDiff("same\n", "same\n")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails, then implement `src/diff.ts`**

Run: `npx vitest run test/diff.test.ts` — Expected: FAIL, cannot resolve `../src/diff.js`.

```ts
/** Minimal LCS line diff. Inputs are small (hook scripts), so O(n*m) is fine. */
export function lineDiff(before: string, after: string): string[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const out: string[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      out.push(`- ${a[i++]}`);
    } else {
      out.push(`+ ${b[j++]}`);
    }
  }
  while (i < a.length) out.push(`- ${a[i++]}`);
  while (j < b.length) out.push(`+ ${b[j++]}`);
  return out;
}
```

Run: `npx vitest run test/diff.test.ts` — Expected: PASS.

- [ ] **Step 3: Write the failing install test**

`test/install.test.ts`:
```ts
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { inHome, inProject, makeWorkspace, runKit, type Answers, type Workspace } from "./cli-helpers.js";
import { git, snapshotTree } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[], answers?: Answers) => runKit(args, { cwd: ws.project, home: ws.home, answers });
const readJson = (path: string) => JSON.parse(readFileSync(path, "utf8"));

beforeEach(() => {
  ws = makeWorkspace();
});

describe("kit init", () => {
  it("installs a profile non-interactively at both scopes", async () => {
    const r = await kit(["init", "--profile", "dev", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.asked).toEqual([]);

    expect(existsSync(inProject(ws, ".claude/skills/alpha-skill/SKILL.md"))).toBe(true);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8")).toContain('Greeting is "hi dev"');
    expect(readFileSync(inProject(ws, "docs/context/INDEX.md"), "utf8")).toContain("Areas: api");
    expect(readJson(inProject(ws, ".mcp.json")).mcpServers["alpha-mcp"].command).toBe("alpha-mcp");
    const settings = readJson(inProject(ws, ".claude/settings.json"));
    expect(settings.hooks.PreToolUse[0].hooks[0].command)
      .toBe('node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/alpha/check.mjs');

    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.profile).toBe("dev");
    expect(lock.modules.alpha).toMatchObject({ catalog: "public", version: "1.0.0", config: { greeting: "hi dev", areas: ["api"] } });
    expect(lock.modules.alpha.scaffolded).toEqual(["docs/context/INDEX.md"]);
    expect(lock.catalogs.public).toEqual({ url: ws.publicRepo, sha: git(ws.publicRepo, "rev-parse", "HEAD") });
    expect(lock.createdFiles).toEqual([".claude/settings.json", ".mcp.json", "CLAUDE.md"]);

    expect(existsSync(inHome(ws, ".claude/kit/hooks/beta/guard.mjs"))).toBe(true);
    expect(readJson(inHome(ws, ".claude/settings.json")).hooks.PreToolUse[0].hooks[0].command)
      .toBe(`node "${ws.home}/.claude/kit/hooks/beta/guard.mjs"`);
    expect(readJson(inHome(ws, ".config/harness-kit/lock.json")).modules.beta.version).toBe("0.2.0");
  });

  it("installed hooks actually run from their installed location", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const result = spawnSync(process.execPath, [inProject(ws, ".claude/kit/hooks/alpha/check.mjs")], {
      encoding: "utf8",
      input: JSON.stringify({ hook_event_name: "PreToolUse", tool_name: "Bash", session_id: "s", cwd: ws.project,
                              tool_input: { command: "echo alpha-deny-me" } }),
    });
    expect(JSON.parse(result.stdout).hookSpecificOutput).toMatchObject({
      permissionDecision: "deny", permissionDecisionReason: "alpha (hi dev) blocked this command" });
  });

  it("requires a profile when non-interactive", async () => {
    expect(await kit(["init", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("--yes needs --profile") });
  });

  it("walks through profile, module checklist, config and confirmation", async () => {
    const r = await kit(["init"], {
      select: ["dev"], multiselect: [["public:alpha"]], text: ["howdy", "api, firmware"], confirm: [true] });
    expect(r.code).toBe(0);
    expect(r.asked).toEqual([
      "Profile", "Modules to install", "alpha › Greeting", "alpha › Areas (comma-separated)",
      "Apply these changes to project scope?"]);
    expect(readJson(inProject(ws, ".claude/kit/config/alpha.json")).values).toEqual({ greeting: "howdy", areas: ["api", "firmware"] });
    expect(existsSync(inHome(ws, ".claude"))).toBe(false); // beta was unticked
  });

  it("writes nothing on --dry-run or when the user declines", async () => {
    const before = snapshotTree(ws.project);
    const dry = await kit(["init", "--profile", "dev", "--yes", "--dry-run"]);
    expect(dry.output).toContain("+ .claude/skills/alpha-skill/SKILL.md");
    expect(dry.output).toContain("dry run: nothing written");
    await kit(["init", "--profile", "dev"], { multiselect: [["public:alpha"]], confirm: [false] });
    expect(snapshotTree(ws.project)).toEqual(before);
  });

  it("preserves hand-written settings", async () => {
    mkdirSync(inProject(ws, ".claude"));
    writeFileSync(inProject(ws, ".claude/settings.json"),
      `{\n  "permissions": { "allow": ["Bash(npm test)"] },\n  "hooks": {\n    "PreToolUse": [\n      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }\n    ]\n  }\n}\n`);
    await kit(["init", "--profile", "dev", "--yes"]);
    const text = readFileSync(inProject(ws, ".claude/settings.json"), "utf8");
    expect(text).toContain(`"permissions": { "allow": ["Bash(npm test)"] },`);
    expect(text).toContain(`{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }`);
    expect(JSON.parse(text).hooks.PreToolUse).toHaveLength(2);
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).createdFiles).not.toContain(".claude/settings.json");
  });

  it("explains how to add a catalog when none is configured", async () => {
    const r = await runKit(["init", "--profile", "dev", "--yes"], { cwd: ws.project, home: inHome(ws, "empty") });
    expect(r).toMatchObject({ code: 1, output: expect.stringContaining("kit catalog add") });
  });
});

describe("kit add", () => {
  it("installs a module at a chosen scope and shares the runtime shim", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const r = await kit(["add", "beta", "--scope", "project", "--yes"]);
    expect(r.code).toBe(0);
    const settings = readJson(inProject(ws, ".claude/settings.json"));
    expect(settings.hooks.PreToolUse.map((e: { matcher: string }) => e.matcher)).toEqual(["Bash", "Agent"]);
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    const owners = Object.entries(lock.modules)
      .filter(([, m]) => (m as { owned: { files: { path: string }[] } }).owned.files.some((f) => f.path === ".claude/kit/runtime.mjs"))
      .map(([name]) => name);
    expect(owners.sort()).toEqual(["alpha", "beta"]);
  });

  it("prompts for config and rejects unknown modules and unsupported scopes", async () => {
    const r = await kit(["add", "beta"], { select: ["block"], confirm: [true] });
    expect(r.asked).toEqual(["beta › Mode", "Apply these changes to user scope?"]);
    expect(readJson(inHome(ws, ".claude/kit/config/beta.json")).values).toEqual({ mode: "block" });
    expect(await kit(["add", "nope", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining('module "nope" not found') });
    expect(await kit(["add", "alpha", "--scope", "user", "--yes"]))
      .toMatchObject({ code: 1, output: expect.stringContaining("does not support user scope") });
    expect(await kit(["add"])).toMatchObject({ code: 1, output: expect.stringContaining("usage: kit add") });
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npx vitest run test/install.test.ts`
Expected: FAIL — `unknown command "init"`.

- [ ] **Step 5: Implement `src/pipeline.ts`**

```ts
import { join } from "node:path";
import { getAdapter, type HarnessAdapter } from "./adapters/adapter.js";
import { loadCatalog, type Catalog } from "./catalog/load.js";
import { fetchCatalog } from "./catalog/source.js";
import { lineDiff } from "./diff.js";
import type { Env } from "./env.js";
import { KitError } from "./errors.js";
import { commit, stage, type Conflict, type ScopeRoot, type Staged } from "./executor.js";
import { readLock, writeLock } from "./lockfile.js";
import { backupRoot, catalogCacheDir, findProjectRoot, lockPath } from "./paths.js";
import { planModule, resolveConfig, supportStatus } from "./planner.js";
import { SCOPES, type CatalogLock, type CatalogSource, type Lockfile, type ModuleDef, type Operation, type Scope } from "./types.js";
import { readUserConfig, sourceKey } from "./userconfig.js";

export interface LoadedCatalogs { catalogs: Catalog[]; locks: Record<string, CatalogLock> }

export function loadCatalogs(env: Env, options: { pin: boolean }): LoadedCatalogs {
  const projectRoot = findProjectRoot(env.cwd);
  const wanted = new Map<string, { source: CatalogSource; sha?: string }>();
  const want = (source: CatalogSource, sha?: string) => {
    if (!wanted.has(sourceKey(source))) wanted.set(sourceKey(source), { source, sha });
  };
  for (const scope of SCOPES) {
    for (const { sha, ...source } of Object.values(readLock(lockPath(scope, projectRoot, env.home)).catalogs)) {
      want(source, sha);
    }
  }
  for (const source of readUserConfig(env.home).catalogs) want(source);
  for (const url of env.flags.catalog) {
    want({ url, ...(env.flags.ref ? { ref: env.flags.ref } : {}), ...(env.flags.subdir ? { subdir: env.flags.subdir } : {}) });
  }
  if (wanted.size === 0) {
    throw new KitError("no catalogs configured; run `kit catalog add <git-url>` or pass --catalog <git-url>");
  }

  const loaded: LoadedCatalogs = { catalogs: [], locks: {} };
  for (const { source, sha } of wanted.values()) {
    const fetched = fetchCatalog(source, catalogCacheDir(env.home),
      { offline: env.flags.offline, ...(options.pin && sha ? { sha } : {}) });
    const catalog = loadCatalog(fetched.dir);
    if (loaded.locks[catalog.name]) {
      throw new KitError(`two catalogs are both named "${catalog.name}": ${loaded.locks[catalog.name]!.url} and ${source.url}`);
    }
    loaded.catalogs.push(catalog);
    loaded.locks[catalog.name] = { ...source, sha: fetched.sha };
    for (const bad of catalog.invalid) {
      env.out(`warning: skipping invalid module ${catalog.name}:${bad.name} (${bad.problems.length} problem(s); run kit validate)`);
    }
  }
  return loaded;
}

export function loadCatalogsWithFallback(env: Env): LoadedCatalogs | null {
  try {
    return loadCatalogs(env, { pin: false });
  } catch (err) {
    if (!(err instanceof KitError)) throw err;
    env.out(`warning: ${err.message}`);
  }
  try {
    const offline = loadCatalogs({ ...env, flags: { ...env.flags, offline: true } }, { pin: false });
    env.out("warning: using cached catalogs");
    return offline;
  } catch (err) {
    if (!(err instanceof KitError)) throw err;
    return null;
  }
}

export interface ScopeContext {
  scope: Scope;
  adapter: HarnessAdapter;
  scopeRoot: ScopeRoot;
  lockFile: string;
  backupDir: string;
  lock: Lockfile;
}

export function openScope(scope: Scope, env: Env): ScopeContext {
  const projectRoot = findProjectRoot(env.cwd);
  const adapter = getAdapter(env.flags.harness);
  const lockFile = lockPath(scope, projectRoot, env.home);
  const lock = readLock(lockFile);
  if (Object.keys(lock.modules).length > 0 && lock.harness !== adapter.id) {
    throw new KitError(`${lockFile} was written for harness "${lock.harness}", not "${adapter.id}"`);
  }
  lock.harness = adapter.id;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return {
    scope, adapter, lockFile, lock,
    scopeRoot: { root: scope === "project" ? projectRoot : env.home, allowed: adapter.allowedPrefixes(scope) },
    backupDir: join(backupRoot(scope, projectRoot, env.home), stamp),
  };
}

export function findInstalled(name: string, env: Env): ScopeContext {
  const scopes = (env.flags.scope ? [env.flags.scope] : [...SCOPES]).map((s) => openScope(s, env));
  const hits = scopes.filter((ctx) => ctx.lock.modules[name]);
  if (hits.length === 0) throw new KitError(`module "${name}" is not installed`);
  if (hits.length > 1) throw new KitError(`module "${name}" is installed at project and user scope; pass --scope`);
  return hits[0]!;
}

const isHookCode = (target: string): boolean => target.includes("/kit/hooks/") || target.endsWith("/kit/runtime.mjs");

export async function applyPlan(ctx: ScopeContext, ops: Operation[], env: Env): Promise<Staged | null> {
  const onConflict = async (c: Conflict): Promise<"keep" | "overwrite"> => {
    if (env.flags.yes) return "keep";
    if (c.incoming !== null) for (const line of lineDiff(c.current, c.incoming)) env.out(`    ${line}`);
    const why = c.reason === "modified" ? "was edited since the kit installed it" : "already exists and is not managed by the kit";
    return env.prompter.select(`${c.target} ${why}`, [
      { value: "keep" as const, label: "Keep my version" },
      { value: "overwrite" as const, label: c.incoming === null ? "Delete it" : "Replace it with the kit's version" },
    ], "keep" as const);
  };
  const staged = await stage(ops, { scopeRoot: ctx.scopeRoot, createdFiles: ctx.lock.createdFiles, onConflict });

  env.out(`${ctx.scope} scope (${ctx.scopeRoot.root}):`);
  if (staged.writes.length === 0) env.out("  (no file changes)");
  for (const w of staged.writes) {
    env.out(`  ${w.before === null ? "+" : w.after === null ? "-" : "~"} ${w.target}`);
    if (isHookCode(w.target) && w.before !== null && w.after !== null) {
      for (const line of lineDiff(w.before, w.after)) env.out(`      ${line}`);
    }
  }
  if (staged.writes.some((w) => w.target === ".claude.json")) {
    env.out("  note: ~/.claude.json is also written by Claude Code; close running sessions before applying");
  }
  for (const warning of staged.warnings) env.out(`  warning: ${warning}`);

  if (env.flags.dryRun) {
    env.out("  dry run: nothing written");
    return null;
  }
  if (!env.flags.yes && staged.writes.length > 0
      && !(await env.prompter.confirm(`Apply these changes to ${ctx.scope} scope?`, true))) {
    env.out("  skipped");
    return null;
  }
  commit(staged, ctx.scopeRoot, ctx.backupDir);
  return staged;
}

export interface InstallItem { def: ModuleDef; config: Record<string, unknown>; scope: Scope }

export async function installModules(
  items: InstallItem[], loaded: LoadedCatalogs, env: Env, profile?: string,
): Promise<void> {
  for (const scope of SCOPES) {
    const group = items.filter((item) => item.scope === scope);
    if (group.length === 0) continue;
    const ctx = openScope(scope, env);
    const ops = group.flatMap((item) =>
      planModule({ def: item.def, config: item.config }, scope, ctx.adapter, { home: env.home }, ctx.lock));
    for (const item of group) {
      const support = supportStatus(item.def, ctx.adapter);
      if (support.status === "degraded") {
        env.out(`note: ${item.def.name} runs degraded on ${ctx.adapter.id}; unavailable: ${support.missing.join(", ")}`);
      }
    }
    const staged = await applyPlan(ctx, ops, env);
    if (!staged) continue;

    for (const item of group) {
      const record = staged.records[item.def.name] ?? { owned: { files: [], json: [], blocks: [] }, scaffolded: [] };
      const previous = ctx.lock.modules[item.def.name];
      ctx.lock.modules[item.def.name] = {
        catalog: item.def.catalog,
        version: item.def.version,
        config: resolveConfig(item.def, item.config),
        owned: record.owned,
        scaffolded: [...new Set([...(previous?.scaffolded ?? []), ...record.scaffolded])].sort(),
      };
      ctx.lock.catalogs[item.def.catalog] = loaded.locks[item.def.catalog]!;
    }
    ctx.lock.createdFiles = staged.createdFiles;
    if (profile && scope === "project") ctx.lock.profile = profile;
    writeLock(ctx.lockFile, ctx.lock);
    env.out(`  installed at ${scope} scope: ${group.map((i) => `${i.def.name}@${i.def.version}`).join(", ")}`);
  }
}
```

- [ ] **Step 6: Implement `src/commands/init.ts` and `src/commands/add.ts`**

`src/commands/init.ts`:
```ts
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
```

`src/commands/add.ts`:
```ts
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
```

- [ ] **Step 7: Register the commands in `src/cli.ts`**

Add the imports next to the existing command imports:
```ts
import { addCommand } from "./commands/add.js";
import { initCommand } from "./commands/init.js";
```
and extend `COMMANDS` to:
```ts
const COMMANDS: Record<string, Command> = {
  add: addCommand,
  catalog: catalogCommand,
  init: initCommand,
  validate: validateCommand,
};
```

- [ ] **Step 8: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/diff.ts src/pipeline.ts src/commands/init.ts src/commands/add.ts src/cli.ts test/diff.test.ts test/install.test.ts
git commit -m "feat: install pipeline with init and add commands"
```

---

### Task 13: `remove`, `update`, `config`

**Files:**
- Create: `src/commands/remove.ts`, `src/commands/update.ts`, `src/commands/config.ts`
- Modify: `src/cli.ts` (register three commands)
- Test: `test/lifecycle.test.ts`

**Interfaces:**
- Consumes: `findInstalled`, `openScope`, `applyPlan`, `installModules`, `loadCatalogs` from `src/pipeline.ts`; `planRemove`; `promptConfig`; `resolveModule`; `moduleStateDir`; `writeLock`.
- Produces: `removeCommand`, `updateCommand`, `configCommand` (all `Command`).
- Behaviour:
  - `remove <module…>`: one plan per scope, so a file shared by two removed modules is deleted. Afterwards the module leaves the lock; catalogs no module references any more leave the lock; scaffolded files are listed as left in place; the module's state directory (`~/.config/harness-kit/state/<module>`) is deleted only after confirmation, and kept under `--yes`.
  - `update [module…]`: loads catalogs **unpinned**, re-plans each installed module from its catalog (`<catalog>:<name>`), prints `name old → new`, keeps config values whose keys still exist, and reuses `installModules`. A module that vanished from its catalog is skipped with a warning.
  - `config <module>`: loads catalogs **pinned**, prompts with current values, reuses `installModules`. Under `--yes` it re-renders with the current values.

- [ ] **Step 1: Write the failing test**

`test/lifecycle.test.ts`:
```ts
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { inHome, inProject, makeWorkspace, runKit, type Answers, type Workspace } from "./cli-helpers.js";
import { commitAll } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[], answers?: Answers) => runKit(args, { cwd: ws.project, home: ws.home, answers });
const readJson = (path: string) => JSON.parse(readFileSync(path, "utf8"));
const SKILL = ".claude/skills/alpha-skill/SKILL.md";

function releaseAlpha(edit: (manifest: any) => void, files: Record<string, string | null> = {}): string {
  const dir = join(ws.publicRepo, "modules/alpha");
  const manifest = readJson(join(dir, "module.json"));
  edit(manifest);
  writeFileSync(join(dir, "module.json"), JSON.stringify(manifest, null, 2));
  for (const [rel, content] of Object.entries(files)) {
    if (content === null) rmSync(join(dir, rel));
    else writeFileSync(join(dir, rel), content);
  }
  return commitAll(ws.publicRepo, "release alpha");
}

beforeEach(async () => {
  ws = makeWorkspace();
  await kit(["init", "--profile", "dev", "--yes"]);
});

describe("kit remove", () => {
  it("removes everything the module owns and leaves scaffolded files", async () => {
    const r = await kit(["remove", "alpha", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("left in place (yours now): docs/context/INDEX.md");
    for (const gone of [".claude", ".mcp.json", "CLAUDE.md"]) expect(existsSync(inProject(ws, gone))).toBe(false);
    expect(existsSync(inProject(ws, "docs/context/INDEX.md"))).toBe(true);
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.modules).toEqual({});
    expect(lock.catalogs).toEqual({});
    expect(lock.createdFiles).toEqual([]);
  });

  it("deletes the shared runtime when all its owners are removed together", async () => {
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    await kit(["remove", "alpha", "--yes"]);
    expect(existsSync(inProject(ws, ".claude/kit/runtime.mjs"))).toBe(true); // beta still needs it
    await kit(["add", "alpha", "--yes"]);
    await kit(["remove", "alpha", "beta", "--scope", "project", "--yes"]);
    expect(existsSync(inProject(ws, ".claude"))).toBe(false);
  });

  it("needs --scope when a module is installed at both scopes", async () => {
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    expect(await kit(["remove", "beta", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("pass --scope") });
    expect((await kit(["remove", "beta", "--scope", "user", "--yes"])).code).toBe(0);
    expect(existsSync(inHome(ws, ".claude"))).toBe(false);
    expect(existsSync(inProject(ws, ".claude/kit/hooks/beta/guard.mjs"))).toBe(true);
  });

  it("asks before deleting module state, and keeps it under --yes", async () => {
    const state = inHome(ws, ".config/harness-kit/state/beta");
    mkdirSync(state, { recursive: true });
    await kit(["remove", "beta", "--yes"]);
    expect(existsSync(state)).toBe(true);
    await kit(["add", "beta", "--yes"]);
    const r = await kit(["remove", "beta"], { confirm: [true, true] });
    expect(r.asked).toContain("Delete beta's saved state?");
    expect(existsSync(state)).toBe(false);
  });

  it("rejects modules that are not installed", async () => {
    expect(await kit(["remove", "gamma", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });
});

describe("kit update", () => {
  it("moves to the new version, drops retired contributions, and shows hook diffs", async () => {
    const original = readFileSync(join(ws.publicRepo, "modules/alpha/hooks/check.mjs"), "utf8");
    const sha = releaseAlpha((m) => {
      m.version = "1.1.0";
      m.contributes.hooks = m.contributes.hooks.filter((h: { run: string }) => h.run !== "hooks/start.mjs");
    }, { "hooks/start.mjs": null, "hooks/check.mjs": original + "// v1.1\n" });

    const r = await kit(["update", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("alpha 1.0.0 → 1.1.0");
    expect(r.output).toContain("beta 0.2.0 (up to date)");
    expect(r.output).toContain("+ // v1.1");
    expect(r.output).toContain("- .claude/kit/hooks/alpha/start.mjs");
    expect(existsSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"))).toBe(false);
    expect(readJson(inProject(ws, ".claude/settings.json")).hooks.SessionStart).toBeUndefined();
    const lock = readJson(inProject(ws, ".harness-kit/lock.json"));
    expect(lock.modules.alpha.version).toBe("1.1.0");
    expect(lock.modules.alpha.config.greeting).toBe("hi dev");
    expect(lock.catalogs.public.sha).toBe(sha);
    expect(lock.modules.alpha.scaffolded).toEqual(["docs/context/INDEX.md"]);
  });

  it("never silently discards a user's edit", async () => {
    appendFileSync(inProject(ws, SKILL), "\nMY NOTES\n");
    releaseAlpha((m) => { m.version = "1.1.0"; }, { "skills/alpha-skill/SKILL.md": "---\nname: alpha-skill\ndescription: v1.1\n---\n" });
    const r = await kit(["update", "--yes"]);
    expect(r.output).toContain(`warning: kept your version of ${SKILL}`);
    expect(readFileSync(inProject(ws, SKILL), "utf8")).toContain("MY NOTES");
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.version).toBe("1.1.0");
  });

  it("lets the user choose to take the kit's version", async () => {
    appendFileSync(inProject(ws, SKILL), "\nMY NOTES\n");
    releaseAlpha((m) => { m.version = "1.1.0"; }, { "skills/alpha-skill/SKILL.md": "v1.1 skill\n" });
    const r = await kit(["update", "alpha"], { select: ["overwrite"], confirm: [true] });
    expect(r.asked[0]).toContain("was edited since the kit installed it");
    expect(readFileSync(inProject(ws, SKILL), "utf8")).toBe("v1.1 skill\n");
  });

  it("add stays pinned to the locked catalog commit until update", async () => {
    releaseAlpha((m) => { m.version = "1.1.0"; });
    await kit(["add", "alpha", "--yes"]);
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.version).toBe("1.0.0");
  });

  it("skips modules that left the catalog, and rejects ones that are not installed", async () => {
    const index = join(ws.publicRepo, "catalog.json");
    writeFileSync(index, readFileSync(index, "utf8").replace('"modules/alpha", ', ""));
    commitAll(ws.publicRepo, "drop alpha");
    const r = await kit(["update", "--yes"]);
    expect(r.code).toBe(0);
    expect(r.output).toContain("warning: alpha is no longer in catalog public; skipped");
    expect(await kit(["update", "gamma", "--yes"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });
});

describe("kit config", () => {
  it("re-prompts with current values and re-renders what depends on them", async () => {
    const r = await kit(["config", "alpha"], { text: ["bonjour", "api"], confirm: [true] });
    expect(r.code).toBe(0);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8")).toContain('Greeting is "bonjour"');
    expect(readJson(inProject(ws, ".claude/kit/config/alpha.json")).values.greeting).toBe("bonjour");
    expect(readJson(inProject(ws, ".harness-kit/lock.json")).modules.alpha.config.greeting).toBe("bonjour");
    expect(readFileSync(inProject(ws, "docs/context/INDEX.md"), "utf8")).toContain("Areas: api"); // scaffold untouched
  });

  it("needs exactly one installed module", async () => {
    expect(await kit(["config"])).toMatchObject({ code: 1, output: expect.stringContaining("usage: kit config") });
    expect(await kit(["config", "gamma"])).toMatchObject({ code: 1, output: expect.stringContaining("not installed") });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/lifecycle.test.ts`
Expected: FAIL — `unknown command "remove"`.

- [ ] **Step 3: Implement the three commands**

`src/commands/remove.ts`:
```ts
import { existsSync, rmSync } from "node:fs";
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { writeLock } from "../lockfile.js";
import { moduleStateDir } from "../paths.js";
import { applyPlan, findInstalled, type ScopeContext } from "../pipeline.js";
import { planRemove } from "../planner.js";

export const removeCommand: Command = async (args, env) => {
  if (args.length === 0) throw new KitError("usage: kit remove <module…> [--scope project|user]");
  const groups = new Map<string, { ctx: ScopeContext; names: string[] }>();
  for (const name of args) {
    const ctx = findInstalled(name, env);
    const group = groups.get(ctx.scope) ?? { ctx, names: [] };
    group.names.push(name);
    groups.set(ctx.scope, group);
  }

  for (const { ctx, names } of groups.values()) {
    const staged = await applyPlan(ctx, planRemove(names, ctx.lock), env);
    if (!staged) continue;
    const left = names.flatMap((name) => ctx.lock.modules[name]!.scaffolded);
    for (const name of names) delete ctx.lock.modules[name];
    const usedCatalogs = new Set(Object.values(ctx.lock.modules).map((m) => m.catalog));
    for (const catalog of Object.keys(ctx.lock.catalogs)) {
      if (!usedCatalogs.has(catalog)) delete ctx.lock.catalogs[catalog];
    }
    if (Object.keys(ctx.lock.modules).length === 0) delete ctx.lock.profile;
    ctx.lock.createdFiles = staged.createdFiles;
    writeLock(ctx.lockFile, ctx.lock);
    env.out(`  removed from ${ctx.scope} scope: ${names.join(", ")}`);
    if (left.length > 0) env.out(`  left in place (yours now): ${left.join(", ")}`);

    for (const name of names) {
      const state = moduleStateDir(env.home, name);
      if (!existsSync(state)) continue;
      if (!env.flags.yes && (await env.prompter.confirm(`Delete ${name}'s saved state?`, false))) {
        rmSync(state, { recursive: true, force: true });
      } else {
        env.out(`  kept saved state in ${state}`);
      }
    }
  }
  return 0;
};
```

`src/commands/update.ts`:
```ts
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
```

`src/commands/config.ts`:
```ts
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
```

- [ ] **Step 4: Register the commands in `src/cli.ts`**

Add the imports:
```ts
import { configCommand } from "./commands/config.js";
import { removeCommand } from "./commands/remove.js";
import { updateCommand } from "./commands/update.js";
```
and extend `COMMANDS` to:
```ts
const COMMANDS: Record<string, Command> = {
  add: addCommand,
  catalog: catalogCommand,
  config: configCommand,
  init: initCommand,
  remove: removeCommand,
  update: updateCommand,
  validate: validateCommand,
};
```

- [ ] **Step 5: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/commands/remove.ts src/commands/update.ts src/commands/config.ts src/cli.ts test/lifecycle.test.ts
git commit -m "feat: remove, update and config commands"
```

---

### Task 14: `status` and `list`

**Files:**
- Create: `src/status.ts`, `src/commands/status.ts`, `src/commands/list.ts`
- Modify: `src/cli.ts` (register two commands)
- Test: `test/status-list.test.ts`

**Interfaces:**
- Consumes: `ScopeContext`, `openScope`, `loadCatalogsWithFallback`; `resolveConfined`; `hashContent`; `hasJsonEntry`, `fromPointer`; `hasBlock`; `supportStatus`.
- Produces:
  - `interface StatusIssue { scope: Scope; module: string; problem: string }`
  - `computeStatus(ctx: ScopeContext, catalogs: Catalog[] | null, vars: Record<string, string | undefined>): StatusIssue[]` — per installed module: owned files `missing` or `modified`; JSON entries and blocks `missing`; `outdated` when the catalog has a different version; `env var X is not set` for each `requires.env`. Catalog-dependent checks are skipped when `catalogs` is `null` or the module is not in them.
  - `statusCommand` — prints issues, adds a `duplicate` issue for modules installed at both scopes, exits 1 when there are issues (for CI).
  - `listCommand` — one line per catalog module: qualified name, version, scopes, support status, install marks.

- [ ] **Step 1: Write the failing test**

`test/status-list.test.ts`:
```ts
import { appendFileSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { inProject, makeWorkspace, runKit, type Workspace } from "./cli-helpers.js";
import { commitAll } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[]) => runKit(args, { cwd: ws.project, home: ws.home });

beforeEach(async () => {
  ws = makeWorkspace();
  process.env.ALPHA_TOKEN = "set";
  await kit(["init", "--profile", "dev", "--yes"]);
});
afterEach(() => {
  delete process.env.ALPHA_TOKEN;
});

describe("kit status", () => {
  it("is clean right after install", async () => {
    expect(await kit(["status"])).toMatchObject({ code: 0, output: expect.stringContaining("ok: 2 modules, no problems") });
  });

  it("reports drift, missing env vars, outdated modules and duplicates, and exits 1", async () => {
    rmSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"));
    appendFileSync(inProject(ws, ".claude/skills/alpha-skill/SKILL.md"), "edit\n");
    writeFileSync(inProject(ws, ".mcp.json"), "{}\n");
    writeFileSync(inProject(ws, "CLAUDE.md"), "# mine\n");
    delete process.env.ALPHA_TOKEN;
    await kit(["add", "beta", "--scope", "project", "--yes"]);
    const manifest = join(ws.publicRepo, "modules/alpha/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace('"1.0.0"', '"1.1.0"'));
    commitAll(ws.publicRepo, "release");

    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    for (const expected of [
      "project alpha: missing .claude/kit/hooks/alpha/start.mjs",
      "project alpha: modified .claude/skills/alpha-skill/SKILL.md",
      "project alpha: missing entry /mcpServers/alpha-mcp in .mcp.json",
      "project alpha: missing block in CLAUDE.md",
      "project alpha: env var ALPHA_TOKEN is not set",
      "project alpha: outdated (1.0.0 installed, 1.1.0 available)",
      "user beta: duplicate (also installed at project scope; the project install wins)",
    ]) expect(r.output).toContain(expected);
  });

  it("still checks files when catalogs are unreachable", async () => {
    rmSync(ws.publicRepo, { recursive: true, force: true });
    rmSync(join(ws.home, ".cache"), { recursive: true, force: true });
    rmSync(inProject(ws, ".claude/kit/hooks/alpha/start.mjs"));
    const r = await kit(["status"]);
    expect(r.code).toBe(1);
    expect(r.output).toContain("warning:");
    expect(r.output).toContain("missing .claude/kit/hooks/alpha/start.mjs");
  });
});

describe("kit list", () => {
  it("shows catalog modules with support and install marks", async () => {
    const r = await kit(["list"]);
    expect(r.code).toBe(0);
    expect(r.output).toMatch(/public:alpha\s+1\.0\.0\s+project\s+supported\s+installed \(project 1\.0\.0\)/);
    expect(r.output).toMatch(/public:beta\s+0\.2\.0\s+user,project\s+supported\s+installed \(user 0\.2\.0\)/);
  });

  it("marks outdated installs", async () => {
    const manifest = join(ws.publicRepo, "modules/alpha/module.json");
    writeFileSync(manifest, readFileSync(manifest, "utf8").replace('"1.0.0"', '"1.1.0"'));
    commitAll(ws.publicRepo, "release");
    expect((await kit(["list"])).output).toMatch(/public:alpha\s+1\.1\.0.*installed \(project 1\.0\.0, outdated\)/);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/status-list.test.ts`
Expected: FAIL — `unknown command "status"`.

- [ ] **Step 3: Implement `src/status.ts`**

```ts
import { existsSync, readFileSync } from "node:fs";
import type { Catalog } from "./catalog/load.js";
import { resolveConfined } from "./executor.js";
import { hashContent } from "./hash.js";
import { fromPointer, hasJsonEntry } from "./ops/json-merge.js";
import { hasBlock } from "./ops/marked-block.js";
import type { ScopeContext } from "./pipeline.js";
import type { Scope } from "./types.js";

export interface StatusIssue { scope: Scope; module: string; problem: string }

export function computeStatus(
  ctx: ScopeContext, catalogs: Catalog[] | null, vars: Record<string, string | undefined>,
): StatusIssue[] {
  const issues: StatusIssue[] = [];
  const read = (target: string): string | null => {
    const absolute = resolveConfined(ctx.scopeRoot, target);
    return existsSync(absolute) ? readFileSync(absolute, "utf8") : null;
  };

  for (const [module, locked] of Object.entries(ctx.lock.modules)) {
    const report = (problem: string) => issues.push({ scope: ctx.scope, module, problem });

    for (const file of locked.owned.files) {
      const content = read(file.path);
      if (content === null) report(`missing ${file.path}`);
      else if (hashContent(content) !== file.hash) report(`modified ${file.path}`);
    }
    for (const entry of locked.owned.json) {
      const content = read(entry.file);
      let present = false;
      try {
        present = content !== null && hasJsonEntry(content, entry.file, fromPointer(entry.pointer), entry.match);
      } catch {
        present = false; // unparseable file: the entry is effectively gone
      }
      if (!present) report(`missing entry ${entry.pointer} in ${entry.file}`);
    }
    for (const block of locked.owned.blocks) {
      const content = read(block.file);
      if (content === null || !hasBlock(content, block.id)) report(`missing block in ${block.file}`);
    }

    const def = catalogs?.find((c) => c.name === locked.catalog)?.modules.find((m) => m.name === module);
    if (!def) continue;
    for (const name of def.requires.env) {
      if (!vars[name]) report(`env var ${name} is not set`);
    }
    if (def.version !== locked.version) report(`outdated (${locked.version} installed, ${def.version} available)`);
  }
  return issues;
}
```

- [ ] **Step 4: Implement the two commands**

`src/commands/status.ts`:
```ts
import type { Command } from "../env.js";
import { loadCatalogsWithFallback, openScope } from "../pipeline.js";
import { computeStatus } from "../status.js";
import { SCOPES } from "../types.js";

export const statusCommand: Command = async (_args, env) => {
  const contexts = SCOPES.map((scope) => openScope(scope, env));
  const installed = contexts.reduce((n, ctx) => n + Object.keys(ctx.lock.modules).length, 0);
  if (installed === 0) {
    env.out("nothing installed");
    return 0;
  }
  const catalogs = loadCatalogsWithFallback(env)?.catalogs ?? null;
  const issues = contexts.flatMap((ctx) => computeStatus(ctx, catalogs, process.env));

  const [project, user] = contexts;
  for (const module of Object.keys(user!.lock.modules)) {
    if (project!.lock.modules[module]) {
      issues.push({ scope: "user", module, problem: "duplicate (also installed at project scope; the project install wins)" });
    }
  }
  for (const issue of issues) env.out(`${issue.scope} ${issue.module}: ${issue.problem}`);
  if (issues.length === 0) env.out(`ok: ${installed} modules, no problems`);
  return issues.length > 0 ? 1 : 0;
};
```

`src/commands/list.ts`:
```ts
import type { Command } from "../env.js";
import { KitError } from "../errors.js";
import { loadCatalogsWithFallback, openScope } from "../pipeline.js";
import { supportStatus } from "../planner.js";
import { SCOPES } from "../types.js";

export const listCommand: Command = async (_args, env) => {
  const loaded = loadCatalogsWithFallback(env);
  if (!loaded) throw new KitError("no catalogs available; run `kit catalog add <git-url>`");
  const contexts = SCOPES.map((scope) => openScope(scope, env));
  const adapter = contexts[0]!.adapter;

  const rows = loaded.catalogs.flatMap((c) => c.modules).map((m) => {
    const marks = contexts.flatMap((ctx) => {
      const locked = ctx.lock.modules[m.name];
      if (!locked || locked.catalog !== m.catalog) return [];
      return [`${ctx.scope} ${locked.version}${locked.version === m.version ? "" : ", outdated"}`];
    });
    return [`${m.catalog}:${m.name}`, m.version, m.scopes.join(","), supportStatus(m, adapter).status,
            marks.length > 0 ? `installed (${marks.join("; ")})` : "-", m.description];
  });
  const widths = [0, 1, 2, 3, 4].map((i) => Math.max(...rows.map((r) => r[i]!.length)));
  for (const row of rows) {
    env.out(row.map((cell, i) => (i < widths.length ? cell.padEnd(widths[i]! + 2) : cell)).join("").trimEnd());
  }
  return 0;
};
```

- [ ] **Step 5: Register the commands in `src/cli.ts`**

Add the imports:
```ts
import { listCommand } from "./commands/list.js";
import { statusCommand } from "./commands/status.js";
```
and extend `COMMANDS` to its final form:
```ts
const COMMANDS: Record<string, Command> = {
  add: addCommand,
  catalog: catalogCommand,
  config: configCommand,
  init: initCommand,
  list: listCommand,
  remove: removeCommand,
  status: statusCommand,
  update: updateCommand,
  validate: validateCommand,
};
```

- [ ] **Step 6: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/status.ts src/commands/status.ts src/commands/list.ts src/cli.ts test/status-list.test.ts
git commit -m "feat: status and list commands"
```

---

### Task 15: End-to-end success criteria, README, manual acceptance

This task adds no production code unless a test exposes a bug. It proves the spec's five success criteria through the public CLI surface. (Criterion 3 is already covered by `test/lifecycle.test.ts` "never silently discards a user's edit"; criterion 5 by `test/planner.test.ts` "refuses an unsupported module before producing any operation".)

**Files:**
- Create: `README.md`
- Test: `test/e2e.test.ts`

**Interfaces:**
- Consumes: `runKit`, `makeWorkspace`, `snapshotTree`, `makeGitCatalog`, `FIXTURES`.
- Produces: nothing new.

- [ ] **Step 1: Write the end-to-end test**

`test/e2e.test.ts`:
```ts
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { inProject, makeWorkspace, runKit, type Workspace } from "./cli-helpers.js";
import { FIXTURES, makeGitCatalog, snapshotTree, tempDir } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[]) => runKit(args, { cwd: ws.project, home: ws.home });
// The kit's own state dir and scaffolded files are excluded from "byte-identical" by design.
const projectTree = () => snapshotTree(ws.project, [".harness-kit", "docs/context"]);
const homeTree = () => snapshotTree(ws.home, [".config", ".cache"]);

const HAND_WRITTEN = {
  ".claude/settings.json":
    `{\n    "permissions": { "allow": ["Bash(npm test)"], "deny": [] },\n    "hooks": {\n        "PreToolUse": [\n            { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }\n        ]\n    },\n    "model": "sonnet"\n}\n`,
  ".mcp.json": `{"mcpServers":{"mine":{"command":"my-mcp"}}}`,
  "CLAUDE.md": "# My project\n\nHouse rules.\n",
  "src/index.js": "console.log('untouched');\n",
};

beforeEach(() => {
  ws = makeWorkspace();
});

describe("success criteria", () => {
  it("1+2: init then remove leaves an empty repo byte-identical", async () => {
    const [project, home] = [projectTree(), homeTree()];
    expect((await kit(["init", "--profile", "dev", "--yes"])).code).toBe(0);
    expect(projectTree()).not.toEqual(project);
    expect((await kit(["status"])).output).not.toContain("missing");
    expect((await kit(["remove", "alpha", "beta", "--yes"])).code).toBe(0);
    expect(projectTree()).toEqual(project);
    expect(homeTree()).toEqual(home);
  });

  it("1+2: works on a repo with hand-written config, keeps it intact, and round-trips", async () => {
    for (const [rel, content] of Object.entries(HAND_WRITTEN)) {
      mkdirSync(inProject(ws, rel, ".."), { recursive: true });
      writeFileSync(inProject(ws, rel), content);
    }
    const before = projectTree();
    expect((await kit(["init", "--profile", "dev", "--yes"])).code).toBe(0);

    const settings = JSON.parse(readFileSync(inProject(ws, ".claude/settings.json"), "utf8"));
    expect(settings.permissions).toEqual({ allow: ["Bash(npm test)"], deny: [] });
    expect(settings.model).toBe("sonnet");
    expect(settings.hooks.PreToolUse[0].hooks[0].command).toBe("echo mine");
    expect(Object.keys(JSON.parse(readFileSync(inProject(ws, ".mcp.json"), "utf8")).mcpServers)).toEqual(["mine", "alpha-mcp"]);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8").startsWith("# My project\n\nHouse rules.\n")).toBe(true);

    await kit(["update", "--yes"]); // an update with nothing new must not disturb anything either
    expect((await kit(["remove", "alpha", "--yes"])).code).toBe(0);
    expect(projectTree()).toEqual(before);
  });

  it("2: applying the same install twice changes nothing", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const once = snapshotTree(ws.project, [".harness-kit/backup"]);
    const again = await kit(["init", "--profile", "dev", "--yes"]);
    expect(again.output).toContain("(no file changes)");
    expect(snapshotTree(ws.project, [".harness-kit/backup"])).toEqual(once);
  });

  it("4: a company catalog's profile can bundle a public module", async () => {
    const company = makeGitCatalog(FIXTURES.company);
    expect((await kit(["catalog", "add", company])).code).toBe(0);
    const r = await kit(["init", "--profile", "industrial", "--yes"]);
    expect(r.code).toBe(0);
    const lock = JSON.parse(readFileSync(inProject(ws, ".harness-kit/lock.json"), "utf8"));
    expect(Object.keys(lock.modules).sort()).toEqual(["alpha", "gamma"]);
    expect(Object.keys(lock.catalogs).sort()).toEqual(["company", "public"]);
    const claudeMd = readFileSync(inProject(ws, "CLAUDE.md"), "utf8");
    expect(claudeMd).toContain("<!-- kit:alpha:start -->");
    expect(claudeMd).toContain("Company rules apply.");
  });

  it("a teammate's clone needs no user config: the project lock names its catalogs", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const teammate = { cwd: ws.project, home: tempDir("kit-teammate-") };
    expect((await runKit(["status"], teammate)).output).not.toContain("no catalogs");
    expect((await runKit(["add", "beta", "--scope", "project", "--yes"], teammate)).code).toBe(0);
  });
});
```

- [ ] **Step 2: Run the full suite**

Run: `npm test && npm run typecheck`
Expected: PASS. If the round-trip assertions fail, diff the two snapshots key by key (`Object.keys` first, then `JSON.stringify` of the differing file) and fix the primitive responsible (`src/ops/json-merge.ts`, `src/ops/marked-block.ts`, or directory pruning in `src/executor.ts`). Do not weaken the assertion or widen the exclusion list.

- [ ] **Step 3: Write `README.md`**

````markdown
# harness-kit

A managed starter kit for coding-agent harnesses. It installs curated **modules**
— skills, hooks, MCP server config, instruction fragments, scaffolded docs — into
your harness, chosen by **profile**, and records what it installed so modules can be
updated, removed and audited. Claude Code is supported today; the module format is
harness-neutral.

## Quick start

```bash
npx harness-kit catalog add <git-url-of-a-catalog>   # once per machine
cd your-project
npx harness-kit init                                  # pick a profile, tick modules, answer config questions
npx harness-kit status                                # drift, outdated modules, missing env vars (exit 1 on problems)
```

Non-interactive (CI, onboarding scripts): `npx harness-kit init --profile backend-dev --yes`.

| Command | Purpose |
|---|---|
| `init [--profile P]` | Choose a profile and modules, then install |
| `add <module…>` / `remove <module…>` | Install or uninstall modules (`--scope project\|user`) |
| `update [module…]` | Move to the latest catalog version; shows a diff of every changed hook script first |
| `config <module>` | Change a module's settings |
| `list` / `status` | What exists, what is installed, what has drifted |
| `catalog list\|add\|remove` | Manage catalog sources (`--ref`, `--subdir`) |
| `validate <path>` | Lint a catalog; run it in the catalog's CI |

Every mutating command prints its plan first and accepts `--dry-run` and `--yes`.

## What the kit guarantees

- **Nothing from a catalog runs at install time.** Modules are data. Hook scripts run
  later, inside your harness, and `update` shows you their diff before applying.
- **It only touches what it owns.** Owned files are tracked by hash in
  `.harness-kit/lock.json` (commit it). If you edited one, the kit asks; under `--yes` it
  keeps your version and warns. Entries merged into `settings.json` / `.mcp.json` and the
  block in `CLAUDE.md` are removed individually; the rest of those files is left
  byte-for-byte alone.
- **Scaffolded files are yours.** They are created once and never touched again.
- **Writes are all-or-nothing**, with originals backed up under `.harness-kit/backup/`.
- Modules can never write outside the project (or, at user scope, outside `~/.claude/`
  and `~/.claude.json`), nor into `.git/` or `.harness-kit/`.
- The project lock pins each catalog to a commit. `add` and `config` stay on that commit;
  only `update` moves it.

## Writing a module

A catalog is a git repo (or a subdirectory of one) with a `catalog.json`:

```json
{ "name": "company", "modules": ["modules/plm-mcp"], "profiles": ["profiles/industrial.json"] }
```

Start from [`catalog/modules/kit-example`](catalog/modules/kit-example). A module is a folder:

```
module.json          manifest (below)
skills/<name>/       Agent Skills folders, copied verbatim
hooks/*.mjs          Node scripts; the whole folder is copied
instructions/*.md    fragments merged into CLAUDE.md; {{placeholders}} rendered
templates/…          scaffold sources; {{placeholders}} rendered
```

```jsonc
{
  "name": "budget-guard", "version": "0.1.0", "description": "…",
  "scopes": ["user", "project"],              // first one is the default
  "requires": { "capabilities": [], "optional": [], "env": ["SOME_TOKEN"] },
  "config": { "limit": { "type": "number", "default": 20, "prompt": "Daily limit (USD)" } },
  "contributes": {
    "skills": ["skills/budget-status"],
    "hooks": [{ "event": "pre-tool-use", "match": { "tool": "shell" }, "run": "hooks/check.mjs", "onError": "allow" }],
    "instructions": ["instructions/budget.md"],
    "mcpServers": { "name": { "command": "…", "env": { "TOKEN": "${SOME_TOKEN}" } } },
    "scaffold": [{ "from": "templates/docs", "to": "docs/context" }]   // project scope only
  }
}
```

- Config types: `string`, `number`, `boolean`, `enum` (with `values`), `string[]`.
  Placeholders: `{{config.<key>}}`, `{{module.name}}`, `{{module.version}}`.
- Events: `pre-tool-use`, `post-tool-use`, `session-start`, `user-prompt`, `subagent-start`, `stop`.
  Tool matchers: `*`, `subagent`, `shell`, `edit`.
- Never put secrets in a module. Reference environment variables and list them in `requires.env`.

A hook script talks only to the kit runtime, never to harness-specific payloads:

```js
import { run } from "../../runtime.mjs";

run(({ event, tool, session, config, allow, warn, ask, deny }) => {
  // tool: { kind: "subagent" | "shell" | "edit" | "other", name, input } or null
  // session: { id, cwd, transcriptPath }
  if (tool?.kind === "shell" && String(tool.input.command).includes("rm -rf /")) return deny("no");
  return allow();
});
```

`onError: "allow"` (default) means a crashing hook never blocks work; use `"deny"` for
security hooks that must fail closed. If the same module is installed at user and project
scope, the project install wins and the user-scope hook stands down.

Profiles bundle modules, possibly from other catalogs:

```json
{ "name": "industrial", "description": "…",
  "modules": { "budget-guard": { "scope": "user", "config": { "limit": 10 } }, "public:kit-example": {} } }
```

## Development

```bash
npm install && npm test && npm run typecheck && npm run build
node dist/bin.js validate catalog
```
````

- [ ] **Step 4: Build and smoke-test the real binary**

Run:
```bash
npm run build
TMP_HOME=$(mktemp -d) && TMP_PROJECT=$(mktemp -d) && git -C "$TMP_PROJECT" init -q
(cd "$TMP_PROJECT" && HARNESS_KIT_HOME="$TMP_HOME" node "$OLDPWD/dist/bin.js" init --profile example --yes --catalog "$OLDPWD" --subdir catalog)
(cd "$TMP_PROJECT" && HARNESS_KIT_HOME="$TMP_HOME" node "$OLDPWD/dist/bin.js" status)
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo kit-example-deny-me"},"cwd":"'"$TMP_PROJECT"'"}' | node "$TMP_PROJECT/.claude/kit/hooks/kit-example/guard.mjs"
```
Expected: `init` prints a plan and `installed at project scope: kit-example@0.1.0`; `status` prints `ok: 1 modules, no problems`; the last command prints JSON containing `"permissionDecision":"deny"`. (This uses the working tree as the catalog, so everything under `catalog/` must be committed first.)

- [ ] **Step 5: Commit**

```bash
git add README.md test/e2e.test.ts
git commit -m "test: end-to-end success criteria; docs: README"
```

- [ ] **Step 6: Manual acceptance in a real Claude Code session (needs a human)**

This cannot be automated. Ask the user to do it, or do it with them, and report the outcome honestly — including "not done".

1. In the `$TMP_PROJECT` from Step 4 (or any scratch repo with kit-example installed), start `claude`.
2. At session start, the message `kit-example is active: hello` appears.
3. `/skills` (or asking "is the harness kit working?") shows the `kit-example` skill.
4. Ask Claude to run `echo kit-example-deny-me`. The Bash call is denied with `kit-example blocked this command`.
5. Ask Claude to run `echo fine`. It runs normally.
6. Exit, run `kit remove kit-example --yes`, start `claude` again: no message, no skill, nothing blocked.

If step 2, 3 or 4 fails, the Claude Code hook or skill contract differs from the spec's appendix. Re-check the current Claude Code hooks documentation, fix `assets/claude-code/runtime.mjs` or `src/adapters/claude-code.ts`, and add a regression test to `test/runtime.test.ts` or `test/claude-code-adapter.test.ts`.
