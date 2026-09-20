import { existsSync, readFileSync } from "node:fs";
import type { Catalog } from "./catalog/load.js";
import { KitError } from "./errors.js";
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
    // A single owned entry can be unreadable on its own terms (an unsafe path from a hand-edited
    // lockfile, a block with a start marker but no end marker, ...): resolveConfined/hasBlock throw
    // a KitError for that one entry. Report it like any other issue and keep checking the rest of
    // this module and the other scope, instead of letting the error escape and abort `kit status`.
    const guarded = (label: string, check: () => void) => {
      try {
        check();
      } catch (err) {
        if (!(err instanceof KitError)) throw err;
        report(`${label}: ${err.message}`);
      }
    };

    for (const file of locked.owned.files) {
      guarded(file.path, () => {
        const content = read(file.path);
        if (content === null) report(`missing ${file.path}`);
        else if (hashContent(content) !== file.hash) report(`modified ${file.path}`);
      });
    }
    for (const entry of locked.owned.json) {
      guarded(entry.file, () => {
        const content = read(entry.file);
        let present = false;
        try {
          present = content !== null && hasJsonEntry(content, entry.file, fromPointer(entry.pointer), entry.match);
        } catch {
          present = false; // unparseable file: the entry is effectively gone
        }
        if (!present) report(`missing entry ${entry.pointer} in ${entry.file}`);
      });
    }
    for (const block of locked.owned.blocks) {
      guarded(block.file, () => {
        const content = read(block.file);
        if (content === null || !hasBlock(content, block.id)) report(`missing block in ${block.file}`);
      });
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
