# Example corporate catalog

A harnessctl catalog is a git repo (or a subfolder of one) with a `catalog.toml`
listing item folders. Each item folder has an `item.toml` and its payload files.

- **skill**: one `SKILL.md` folder shared by every harness listed in `[skill].harnesses`.
- **hook** / **plugin**: one `[variants.<harness>]` table per supported harness
  (`claude-code`, `opencode`). Variant types:
  - `files`: copy files into the harness folder (`files = { "<source>" = "<destination>" }`);
    for Claude Code, `[variants.claude-code.settings]` holds `hooks` merged into `settings.json`.
    `{scope_dir}` expands to `~/.claude` / `<project>/.claude` (or the opencode folder).
  - `claude-plugin`: `marketplace` (git URL), `marketplace_name`, `plugin`.
  - `npm-plugin`: `package`, added to the `plugin` array of `opencode.json`.

Check a catalog with `harnessctl validate <path>`; run it in the catalog's CI.
