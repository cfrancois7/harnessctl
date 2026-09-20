// Harness Kit hook runtime for Claude Code. Copied into <scope>/.claude/kit/ and owned by the kit.
// Node built-ins only: this file runs inside other people's projects.
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Node resolves import.meta.url through symlinks, so the script path must be resolved the same
// way: otherwise a kit directory reached through a symlink yields a module name of ".." and the
// hook silently degrades into "allow".
const KIT_DIR = dirname(fileURLToPath(import.meta.url));
const realPath = (path) => {
  try {
    return realpathSync(path);
  } catch {
    return resolve(path);
  }
};

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
  const script = realPath(process.argv[1]);
  const [moduleName, ...rest] = relative(join(KIT_DIR, "hooks"), script).split(sep);
  const scriptKey = rest.join("/");
  // A hook declared onError "deny" is registered with this argument, so the fail-closed policy
  // survives a config file that cannot be read or parsed (the policy also lives in that file).
  const denyOnError = process.argv.includes("--kit-on-error=deny");
  let settings = { scope: "project", onError: {}, values: {} };
  let raw = {};
  let outcome;
  try {
    // The payload first: knowing the event is what lets a failure below deny in the event's own
    // encoding instead of falling back to exit 2.
    raw = JSON.parse(readFileSync(0, "utf8") || "{}");
    settings = JSON.parse(readFileSync(join(KIT_DIR, "config", `${moduleName}.json`), "utf8"));
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
    outcome = denyOnError || settings.onError?.[scriptKey] === "deny"
      ? deny(`kit hook ${moduleName}/${scriptKey} failed: ${error?.message ?? error}`)
      : allow();
  }
  process.exitCode = emit(outcome, raw.hook_event_name);
}
