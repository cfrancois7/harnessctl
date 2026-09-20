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
      // A fail-closed hook carries its policy in the command, so that it still denies when its
      // config file (which also records onError) is unreadable. `commandContains` is unaffected.
      const policy = hook.onError === "deny" ? " --kit-on-error=deny" : "";
      const command = scope === "project"
        ? `node "$CLAUDE_PROJECT_DIR"/.claude/${script}${policy}`
        : `node "${env.home.replace(/\\/g, "/")}/.claude/${script}"${policy}`;
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
