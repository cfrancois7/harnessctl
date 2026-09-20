# Harness Kit — Core Design

Date: 2026-09-20
Status: Draft for review
Scope: sub-project 1 of 4 (core engine). Modules get their own specs.

`kit` is a placeholder CLI name throughout; the final name is open and does
not affect the design.

## 1. Purpose

A cookiecutter-like starter kit for coding-agent harnesses. It installs
curated **modules** — skills, hooks, MCP server config, instruction fragments,
and scaffolded files — into a harness, selected by **profile** and adjusted
interactively. Unlike cookiecutter, installs are **managed**: the kit records
what it installed so modules can be updated, removed, and audited.

Audience: internal (company) first, open source later. The engine stays
generic; business modules (industrial context, internal MCPs, security hooks)
live in a separate private catalog.

### Decomposition

| # | Sub-project | Spec |
|---|---|---|
| 1 | Core engine + Claude Code adapter | this document |
| 2 | `subagent-model-guard` module | later |
| 3 | `budget-guard` module | later |
| 4 | `curated-context` module | later |

Section 10 sketches modules 2–4 only far enough to check that the core
contract fits them.

## 2. Decisions

| Topic | Decision |
|---|---|
| Audience | Internal first, public later; generic engine, private business catalog |
| Lifecycle | Managed: install, update, remove, audit via lockfile |
| Install scope | Both project and user scope; each module declares supported scopes |
| Runtime | Node.js ≥ 20, run via `npx`; hook scripts are Node |
| Harnesses | Claude Code adapter only in v1, behind an adapter interface; modules declare required capabilities |
| Selection | Profiles + interactive checklist + per-module config prompts; `--yes` for non-interactive |
| Catalogs | Git repos (URL + ref + optional subdirectory); multiple catalogs; lockfile pins commit SHA |
| Architecture | Own install engine with neutral module format and adapters (not Claude Code plugins) |

### Why not Claude Code's native plugin system

Plugins and marketplaces cover skills, hooks, MCP config, user config, and
team auto-enable through a committed `settings.json`. They do not cover:
scaffolding files into a repo, contributing to `CLAUDE.md`, project-scope
config (plugin config is stored at user scope only), profiles, or lockfile
pinning — and they are Claude-only. Every other harness needs a direct
installer anyway, so a plugin-based design would mean two mechanisms. A
`kit export claude-plugin` command remains possible later without design
changes.

## 3. Architecture

TypeScript CLI. Minimal dependencies: a prompt library and a schema validator.
Catalogs are fetched with the system `git`, so existing SSH/HTTPS
authentication works unchanged.

```
CLI (init · add · remove · update · list · status · config · catalog · validate)
 │
 ├─ catalog    fetch/cache git catalogs; resolve modules and profiles → ModuleDef[]
 ├─ prompts    profile pick, module checklist, per-module config questions
 ├─ planner    PURE: (selected modules + config, lockfile, adapter) → Plan
 │    └─ adapter (claude-code)   contributions → Operation[]; capability report
 ├─ executor   applies Operation[] to disk (dry-run, backup, rollback)
 └─ lockfile   per-scope record of what is installed and what the kit owns
```

### 3.1 Operations

Everything the kit does to disk reduces to a closed set of operations:

| Operation | Effect | Ownership |
|---|---|---|
| `copyFile` | Copy a file from the module to the target | Owned (path + content hash) |
| `renderTemplate` | Render a template with module config, write result | Owned (path + content hash) |
| `mergeJson` | Add keyed entries to a JSON file (`settings.json`, `.mcp.json`) | Owned entries only (file + pointer) |
| `markedBlock` | Insert a delimited block in a text file (`CLAUDE.md`, `AGENTS.md`) | Owned block only (file + block id) |
| `scaffoldOnce` | Create a file only if absent | Recorded, never touched again |

Templates use plain `{{config.<key>}}` and `{{module.<field>}}` substitution
only — no conditionals or loops. `scaffoldOnce` sources pass through the same
substitution. An unknown placeholder is a validation error.

Adapters only **emit** operations. Only the executor touches disk.
Consequences:

- Planner and adapters are pure functions, testable without a filesystem.
- `--dry-run` and the pre-apply diff are a rendering of the plan.
- `remove` inverts the operations recorded in the lockfile; `update` diffs the
  new plan against them. There are no separate code paths.

### 3.2 Adapter interface

```ts
interface HarnessAdapter {
  id: string;                                   // "claude-code"
  detect(root: string): boolean;
  capabilities(): Capability[];
  paths(scope: Scope): AdapterPaths;            // where skills, hooks, config live
  translate(c: Contribution, scope: Scope, ctx: ModuleContext): Operation[];
  runtimeFiles(): SourceFile[];                 // the hook runtime shim for this harness
}
```

Capabilities in v1: `skills`, `instructions`, `mcp`, `pre-tool-hook`,
`post-tool-hook`, `session-hook`, `user-prompt-hook`, `subagent-intercept`,
`usage-telemetry`, `statusline`.

A module whose `requires.capabilities` are not all provided is **unsupported**
and refused before anything is written. A module with unmet
`requires.optional` capabilities is **degraded**: it installs, and `kit list`
and the install plan say which features are inactive.

### 3.3 Claude Code adapter mapping

| Contribution | Project scope | User scope |
|---|---|---|
| Skill | `.claude/skills/<name>/` | `~/.claude/skills/<name>/` |
| Hook script + runtime | `.claude/kit/hooks/<module>/`, `.claude/kit/runtime.mjs` | `~/.claude/kit/…` |
| Hook registration | `mergeJson` into `.claude/settings.json` `hooks` | `~/.claude/settings.json` |
| Module config | `.claude/kit/config/<module>.json` | `~/.claude/kit/config/<module>.json` |
| MCP server | `mergeJson` into `.mcp.json` | `mergeJson` into `~/.claude.json` |
| Instruction fragment | `markedBlock` in `CLAUDE.md` | `markedBlock` in `~/.claude/CLAUDE.md` |
| Scaffold | `scaffoldOnce` relative to repo root | not allowed |

Neutral names map to Claude Code names: event `pre-tool-use` → `PreToolUse`,
`session-start` → `SessionStart`, `user-prompt` → `UserPromptSubmit`,
`post-tool-use` → `PostToolUse`, `subagent-start` → `SubagentStart`,
`stop` → `Stop`; tool matcher `subagent` → `Agent`, `shell` → `Bash`,
`edit` → `Edit|Write`, `*` → all tools.

Hook commands are registered as
`node "$CLAUDE_PROJECT_DIR"/.claude/kit/hooks/<module>/<script>` at project
scope (so the committed `settings.json` works on every teammate's checkout)
and `node <absolute path>` at user scope. Hooks are copied, never run through
`npx`: no startup latency, no network dependency per tool call, works
offline.

`~/.claude.json` is also rewritten by Claude Code itself. For user-scope MCP
entries the executor reads, merges, and atomically renames in one step
immediately before writing, and the plan output advises closing running
sessions first.

### 3.4 Repository layout

```
src/            engine (cli, catalog, prompts, planner, executor, lockfile, adapters/)
catalog/        the generic public catalog (catalog.json, modules/, profiles/)
test/           unit, integration, e2e, fixtures/
docs/
```

The public catalog lives in this repo under `catalog/` for v1. Because a
catalog source is a URL + ref + subdirectory, splitting it out later is a URL
change. The private business catalog is a separate repo from the start.

## 4. Module format

```
modules/budget-guard/
  module.json
  README.md
  skills/budget-status/SKILL.md
  hooks/check.mjs
  instructions/budget.md
  templates/…
```

```jsonc
{
  "name": "budget-guard",
  "version": "0.1.0",                 // semver
  "description": "Token and cost threshold alerts and limits",
  "scopes": ["user", "project"],      // supported scopes; first is the default
  "requires": {
    "capabilities": ["pre-tool-hook", "usage-telemetry"],
    "optional": ["statusline"],
    "env": []                         // env vars that must be set; checked by `kit status`
  },
  "config": {
    "dailyLimitUsd": { "type": "number", "default": 20, "prompt": "Daily limit (USD)" },
    "onLimit": { "type": "enum", "values": ["warn", "block"], "default": "warn",
                 "prompt": "When the limit is reached" }
  },
  "contributes": {
    "skills": ["skills/budget-status"],
    "hooks": [
      { "event": "pre-tool-use", "match": { "tool": "*" },
        "run": "hooks/check.mjs", "onError": "allow" }
    ],
    "instructions": ["instructions/budget.md"],
    "mcpServers": {},
    "scaffold": []                    // [{ "from": "templates/docs", "to": "docs/context" }]
  }
}
```

Config field types in v1: `string`, `number`, `boolean`, `enum`,
`string[]`. No secret type: modules reference environment variables
(`${VAR}` in MCP config, `process.env` in hooks) and declare them in
`requires.env`.

Modules contain **no install-time scripts**. Installation is purely
declarative.

### 4.1 Catalog index and profiles

`catalog.json` at the catalog root: `{ "name": "public", "modules": [...paths], "profiles": [...paths] }`.
The catalog `name` is the qualifier used in `catalog:module`.

```jsonc
// profiles/backend-dev.json
{
  "name": "backend-dev",
  "description": "Backend developer defaults",
  "modules": {
    "budget-guard":         { "scope": "user", "config": { "dailyLimitUsd": 20 } },
    "subagent-model-guard": { "scope": "user" },
    "curated-context":      { "scope": "project" }
  }
}
```

Module names resolve across all configured catalogs. The qualified form
`catalog:module` is required only when two catalogs define the same name;
an unqualified ambiguous name is an error listing the candidates. Profiles in
one catalog may reference modules in another.

In `kit init`, a profile pre-selects modules and pre-fills config; the user
can toggle modules and change values before applying.

### 4.2 Hook runtime contract

Each adapter ships `runtime.mjs`, copied next to the hooks and owned by the
kit. It reads the harness's raw stdin payload and gives hook scripts a
normalized API:

```js
import { run } from "../../runtime.mjs";

run(async ({ event, tool, session, config, allow, warn, ask, deny }) => {
  // tool:    { kind: "subagent" | "shell" | "edit" | "other", name, input }
  // session: { id, cwd, transcriptPath }
  // config:  contents of kit/config/<module>.json
  if (overLimit) return deny("Daily budget reached; raise it with `kit config budget-guard`.");
  return allow();
});
```

`allow / warn / ask / deny` encode the harness's exit codes and JSON output
(for Claude Code: `permissionDecision` of `allow | ask | deny` with a reason,
and a non-blocking message for `warn`). Module hooks never touch
harness-specific payloads, which is what makes them reusable on another
harness.

`run` catches exceptions. The hook's `onError` decides the outcome:
`"allow"` (default) logs to stderr and lets the action proceed, so a buggy
guard never blocks work; `"deny"` fails closed, for security hooks.

`tool.input` is passed through with harness-native field names in v1. A hook
that reads harness-specific fields (for example the sub-agent `model`) is
tied to that harness for those fields; normalizing them is deferred until a
second adapter exists.

**Duplicate scopes.** Claude Code merges hooks from user and project
settings, so a module installed at both scopes would fire twice. Rule: the
project install wins. The user-scope runtime looks for the project lockfile
from `session.cwd` upward and exits with `allow` if the same module is
installed there. `kit status` reports the duplicate.

## 5. Lockfile

Locations (harness-neutral):

- Project: `<repo>/.harness-kit/lock.json` — committed.
- User: `~/.config/harness-kit/lock.json`.

```jsonc
{
  "lockVersion": 1,
  "harness": "claude-code",
  "catalogs": {
    "public":  { "url": "https://…/harness-kit.git", "ref": "main", "subdir": "catalog", "sha": "…" },
    "company": { "url": "git@internal:agents/catalog.git", "ref": "main", "sha": "…" }
  },
  "profile": "backend-dev",
  "modules": {
    "curated-context": {
      "catalog": "public", "version": "0.1.0",
      "config": { "areas": ["api", "firmware"] },
      "owned": {
        "files":  [{ "path": ".claude/skills/context-index/SKILL.md", "hash": "sha256:…" }],
        "json":   [{ "file": ".claude/settings.json", "pointer": "/hooks/SessionStart",
                     "match": { "commandContains": "kit/hooks/curated-context/" } }],
        "blocks": [{ "file": "CLAUDE.md", "id": "kit:curated-context" }]
      },
      "scaffolded": ["docs/context/INDEX.md"]
    }
  }
}
```

Entries in JSON arrays (hook registrations) are identified by `match` — their
command path contains `kit/hooks/<module>/` — never by array index. Entries
in JSON objects (MCP servers) are identified by `pointer` alone.

The kit writes `.harness-kit/.gitignore` containing `backup/`, so backups are
never committed. Marked blocks use
`<!-- kit:<module>:start -->` / `<!-- kit:<module>:end -->` delimiters.

### 5.1 Update and remove rules

| Case | Behaviour |
|---|---|
| Owned file, hash matches lockfile | Replace or delete silently |
| Owned file, modified by the user | Show diff; ask keep or overwrite. With `--yes`: keep and warn |
| Owned file, missing | `update` recreates it; `remove` ignores it |
| Scaffolded file | Never touched after creation; `remove` leaves it and says so |
| JSON entry / marked block | Rewrite only the kit's entries; preserve the rest of the file, including key order and indentation |
| Runtime shim (`runtime.mjs`) | Shared by all modules in the scope; removed when the last module with hooks is removed |

## 6. CLI

| Command | Purpose |
|---|---|
| `kit init [--profile X] [--yes] [--dry-run] [--harness H]` | Detect harness, choose profile, module checklist, config prompts, show plan, apply, write lockfile |
| `kit add <module…> [--scope S]` | Install more modules; same plan → apply pipeline |
| `kit remove <module…> [--scope S]` | Invert the recorded operations |
| `kit update [module…]` | Refetch catalogs; show version changes and a diff of changed hook scripts; apply |
| `kit list` | Catalog modules with installed / outdated marks and supported / degraded / unsupported status |
| `kit status` | Drift report: edited or missing owned files, duplicate scopes, outdated modules, missing env vars. Non-zero exit on problems |
| `kit config <module>` | Re-prompt config, re-render the config file |
| `kit catalog add\|remove\|list` | Manage catalog sources |
| `kit validate <catalog-path>` | Lint every module and profile in a catalog; for catalog CI |

All mutating commands accept `--dry-run` and `--yes`, and print the plan
before applying. Catalog sources are stored in
`~/.config/harness-kit/config.json`; catalogs used by a project are also
recorded in its lockfile so a teammate's `kit update` uses the same sources.
Fetched catalogs are cached under `~/.cache/harness-kit/catalogs/`.

Non-interactive `init` requires `--profile` (or explicit modules through
`add`) and takes config from profile values, then module defaults.

## 7. Safety and trust

The kit places code on developer machines that runs on every tool call.

- **Declarative install.** Nothing from a catalog executes during install,
  update, or remove.
- **Explicit sources, pinned.** Catalogs are added by URL; the lockfile pins
  the commit SHA; `update` shows hook-script diffs before applying.
- **Path confinement.** The executor rejects any operation whose target
  resolves outside the scope root: `..` segments, absolute paths, and
  symlink escapes. Project-scope roots are the repo root; user-scope roots
  are the adapter's user directories and `~/.config/harness-kit`.
- **No secret storage.** Modules reference environment variables only.

## 8. Error handling

- **All-or-nothing writes.** The full plan is validated before any write. An
  unparseable target JSON file aborts the run with a clear message; the kit
  never rewrites a file it cannot parse. Originals are backed up to
  `.harness-kit/backup/<timestamp>/` (user scope: under
  `~/.config/harness-kit/backup/`). A failure during apply rolls back from
  the backup. The lockfile is written last, by atomic rename.
- **Catalog fetch failure.** `list` and `status` fall back to the cache with
  a warning. `init`, `add`, and `update` fail unless `--offline` is given.
- **Invalid module.** Skipped with a warning in listings; an error when
  requested explicitly or referenced by the chosen profile.
- **Unsupported capability.** Refused before any write, naming the missing
  capability.
- **Hook runtime failure.** Governed by `onError` (section 4.2).

Platforms: Linux, macOS, and WSL are tested. Native Windows is best-effort:
Node path handling throughout, no shell-specific syntax, hook commands of the
form `node <path>`.

## 9. Testing

- **Planner and adapter — unit.** Fixture `ModuleDef` + lockfile → expected
  `Operation[]`. Covers schema validation, capability refusal and
  degradation, profile resolution, and catalog name resolution.
- **Merge primitives.** `mergeJson` preserves unknown keys, order, and
  indentation; `markedBlock` insert, replace, remove. Property: applying the
  same plan twice yields an empty second plan.
- **Executor — integration in temp dirs.** Rollback on mid-apply failure,
  path confinement, modified-file detection, atomic lockfile write.
- **End-to-end.** A fixture git catalog created in the test;
  `init → status → update → remove`. Assertion: after `remove`, the tree is
  byte-identical to the starting state, scaffolded files excepted. Run
  against both an empty repo and a repo with hand-written `settings.json`,
  `.mcp.json`, and `CLAUDE.md`.
- **Hook runtime.** Recorded Claude Code stdin payloads in; exit code and
  stdout JSON asserted; `onError` behaviour for both values.
- **Manual acceptance.** Install the fixture module into a real Claude Code
  session and confirm its hook fires and its skill is discovered.

The fixture module exercises all five operation types and both scopes.

## 10. How the modules fit (sketches, not specs)

1. **`subagent-model-guard`** — `pre-tool-use` on `subagent`. Resolves the
   effective sub-agent model: explicit `model` in the tool input → agent
   definition frontmatter → `CLAUDE_CODE_SUBAGENT_MODEL` → inherit. Reads the
   parent model from the transcript tail, because the hook payload does not
   carry it. Compares against a configurable tier table. On violation:
   `ask` (the human confirms — the explicit path) or `deny` with a reason
   that tells the agent to choose a smaller model. Needs
   `subagent-intercept`. Built first: smallest real module, and the one most
   likely to force contract adjustments while they are still cheap.
2. **`budget-guard`** — usage from the transcript JSONL and, when available,
   statusline cost data; per-day state under `~/.config/harness-kit/state/`;
   warns at thresholds, blocks at the limit through `pre-tool-use` and
   `user-prompt`; ships a `budget-status` skill. Needs `usage-telemetry`.
3. **`curated-context`** — `scaffoldOnce` of `docs/context/` (`INDEX.md`,
   `prd/`, `specs/<area>/`, `roadmap.md`, `debt.md`, `merge-log.md`); an
   instruction fragment ("read the index first, load only what the task
   needs"); skills to rebuild the index, log a merged PR, and add a spec
   area; optional `session-start` hook that injects the index. Project scope
   only.

Contract needs surfaced by these sketches and covered by this spec: per-day
state outside owned files (modules write under
`~/.config/harness-kit/state/<module>/`, which the kit never tracks and
`remove` offers to delete), transcript access (`session.transcriptPath`),
and pass-through of harness-native tool input.

## 11. Out of scope for core v1

Codex and opencode adapters; Claude Code plugin export; secret storage;
inter-module dependencies; signed catalogs; auto-update; any UI beyond the
terminal; normalization of harness-native tool input fields.

## 12. Success criteria

1. `npx kit init --profile X --yes` works on an empty repo and on a repo with
   existing hand-written `settings.json`, `.mcp.json`, and `CLAUDE.md`,
   leaving the user's content intact.
2. `init → remove` leaves the tree byte-identical, scaffolded files excepted.
3. `update` never silently discards a user's edit to an owned file.
4. A private SSH catalog and the public catalog work together, including a
   profile in one that references modules in the other.
5. A module that requires a capability the harness lacks is refused, with a
   clear message, before any write.

## Appendix: platform facts this design relies on

Verified against Claude Code, Codex, and opencode documentation on
2026-09-20. Re-verify before implementing the parts that depend on them.

**Claude Code**

- The sub-agent tool is named `Agent`. `PreToolUse` `tool_input` includes
  `prompt`, `description`, `subagent_type`, and `model` only when passed
  explicitly. Model resolution order: per-call `model` → agent frontmatter →
  `CLAUDE_CODE_SUBAGENT_MODEL` → main session model. `PostToolUse` on `Agent`
  reports `resolvedModel` and token totals.
- Hook input carries no usage or cost fields. Cost is available in the
  statusline JSON (`cost.total_cost_usd`), the transcript JSONL, and
  OpenTelemetry (`claude_code.cost.usage`, `claude_code.token.usage`).
  `--max-budget-usd` and `--max-turns` apply to headless mode only; there is
  no native interactive budget limit.
- `PreToolUse` blocks through exit code 2 or
  `hookSpecificOutput.permissionDecision` of `deny | ask | allow` with a
  reason shown to the model.
- Hooks declared at user, project, and local settings levels **merge**; they
  do not override each other.
- MCP config: project scope in `.mcp.json`, user scope in `~/.claude.json`.
- The main session model appears in hook input only for `SessionStart`, and
  not always.

**Portability**

- Skills (`SKILL.md`), `AGENTS.md`-style instructions, and MCP config exist
  natively in Codex and opencode, with different paths and config schemas.
  opencode also reads `.claude/skills`.
- Codex has command hooks with a protocol close to Claude Code's (exit code 2,
  `permissionDecision`); tool coverage is narrower and version-dependent.
  opencode uses JS/TS plugins (`tool.execute.before` throws to block), so its
  adapter would generate a plugin shim around the same hook scripts.
- Neither exposes the resolved sub-agent model or session cost as directly
  as Claude Code; modules needing those will likely be degraded or
  unsupported there.
