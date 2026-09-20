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
