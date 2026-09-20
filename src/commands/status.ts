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
