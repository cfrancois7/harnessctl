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
- **Writes are all-or-nothing**, with originals backed up under `.harness-kit/backup/`. If
  a target changed on disk after the plan was computed, the write is aborted and rolled
  back instead of applied.
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
