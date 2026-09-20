import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
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

let root: string;
let kitDir: string;
let projectDir: string;

const DENY_FLAG = "--kit-on-error=deny";
const configPath = () => join(kitDir, "config/demo.json");
const hookPath = () => join(kitDir, "hooks/demo/h.mjs");

function spawnHook(script: string, input: string, args: string[] = []) {
  const result = spawnSync(process.execPath, [script, ...args], { input, encoding: "utf8" });
  return { code: result.status, stdout: result.stdout.trim(), stderr: result.stderr };
}

function runHook(
  behavior: string, payload: object,
  extra: { scope?: string; onError?: "allow" | "deny"; script?: string; args?: string[] } = {},
) {
  writeFileSync(configPath(), JSON.stringify({
    module: "demo", version: "1.0.0", scope: extra.scope ?? "project",
    onError: { "h.mjs": extra.onError ?? "allow" }, values: { behavior },
  }));
  const input = JSON.stringify({ session_id: "s1", cwd: projectDir, transcript_path: "/t.jsonl", ...payload });
  return spawnHook(extra.script ?? hookPath(), input, extra.args ?? []);
}

const PRE_BASH = { hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: { command: "ls" } };

beforeEach(() => {
  root = tempDir("kit-runtime-");
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

  it("F2a: works identically when the kit directory is reached through a symlink", () => {
    symlinkSync(kitDir, join(root, "kit-link"));
    const linked = join(root, "kit-link/hooks/demo/h.mjs");

    // The handler really runs: its decision (from the module config) comes through unchanged.
    expect(runHook("deny", PRE_BASH, { script: linked })).toEqual(runHook("deny", PRE_BASH));
    expect(JSON.parse(runHook("deny", PRE_BASH, { script: linked }).stdout).hookSpecificOutput)
      .toMatchObject({ permissionDecision: "deny", permissionDecisionReason: "deny:pre-tool-use:shell:s1" });
    // An allow-policy script still fails open, a deny-policy one still fails closed.
    expect(runHook("throw", PRE_BASH, { script: linked })).toMatchObject({ code: 0, stdout: "" });
    const closed = runHook("throw", PRE_BASH, { script: linked, onError: "deny", args: [DENY_FLAG] });
    expect(JSON.parse(closed.stdout).hookSpecificOutput.permissionDecision).toBe("deny");
  });

  it("F2b: fails closed on an unusable config or payload when the command carries the deny flag", () => {
    const input = JSON.stringify({ session_id: "s1", cwd: projectDir, ...PRE_BASH });
    const decision = (stdout: string) => JSON.parse(stdout).hookSpecificOutput;

    rmSync(configPath(), { force: true });
    const missing = spawnHook(hookPath(), input, [DENY_FLAG]);
    expect(decision(missing.stdout).permissionDecision).toBe("deny");
    expect(decision(missing.stdout).permissionDecisionReason).toContain("demo/h.mjs");

    writeFileSync(configPath(), "{ not json");
    expect(decision(spawnHook(hookPath(), input, [DENY_FLAG]).stdout).permissionDecision).toBe("deny");

    writeFileSync(configPath(), JSON.stringify({ module: "demo", onError: {}, values: { behavior: "allow" } }));
    const badStdin = spawnHook(hookPath(), "{ not json", [DENY_FLAG]);
    expect(badStdin.code).toBe(2); // event unknown: the deny encoding for events without a decision format
    expect(badStdin.stderr).toContain("kit hook demo/h.mjs failed");
  });

  it("F2b: the same failures fail open without the deny flag", () => {
    const input = JSON.stringify({ session_id: "s1", cwd: projectDir, ...PRE_BASH });

    rmSync(configPath(), { force: true });
    expect(spawnHook(hookPath(), input)).toMatchObject({ code: 0, stdout: "" });

    writeFileSync(configPath(), "{ not json");
    expect(spawnHook(hookPath(), input)).toMatchObject({ code: 0, stdout: "" });

    writeFileSync(configPath(), JSON.stringify({ module: "demo", onError: {}, values: { behavior: "allow" } }));
    expect(spawnHook(hookPath(), "{ not json")).toMatchObject({ code: 0, stdout: "" });
  });

  it("a user-scope hook yields when the project has the same module installed", () => {
    mkdirSync(join(projectDir, ".harness-kit"));
    writeFileSync(join(projectDir, ".harness-kit/lock.json"), JSON.stringify({ modules: { demo: {} } }));
    expect(runHook("deny", PRE_BASH, { scope: "user" })).toMatchObject({ code: 0, stdout: "" });
    expect(runHook("deny", PRE_BASH, { scope: "project" }).stdout).toContain("deny");
  });
});
