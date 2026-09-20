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
