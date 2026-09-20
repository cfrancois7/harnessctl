import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { inProject, makeWorkspace, runKit, type Workspace } from "./cli-helpers.js";
import { FIXTURES, makeGitCatalog, snapshotTree, tempDir } from "./helpers.js";

let ws: Workspace;
const kit = (args: string[]) => runKit(args, { cwd: ws.project, home: ws.home });
// The kit's own state dir and scaffolded files are excluded from "byte-identical" by design.
const projectTree = () => snapshotTree(ws.project, [".harness-kit", "docs/context"]);
const homeTree = () => snapshotTree(ws.home, [".config", ".cache"]);

const HAND_WRITTEN = {
  ".claude/settings.json":
    `{\n    "permissions": { "allow": ["Bash(npm test)"], "deny": [] },\n    "hooks": {\n        "PreToolUse": [\n            { "matcher": "Bash", "hooks": [{ "type": "command", "command": "echo mine" }] }\n        ]\n    },\n    "model": "sonnet"\n}\n`,
  ".mcp.json": `{"mcpServers":{"mine":{"command":"my-mcp"}}}`,
  "CLAUDE.md": "# My project\n\nHouse rules.\n",
  "src/index.js": "console.log('untouched');\n",
};

beforeEach(() => {
  ws = makeWorkspace();
});

describe("success criteria", () => {
  it("1+2: init then remove leaves an empty repo byte-identical", async () => {
    const [project, home] = [projectTree(), homeTree()];
    expect((await kit(["init", "--profile", "dev", "--yes"])).code).toBe(0);
    expect(projectTree()).not.toEqual(project);
    expect((await kit(["status"])).output).not.toContain("missing");
    expect((await kit(["remove", "alpha", "beta", "--yes"])).code).toBe(0);
    expect(projectTree()).toEqual(project);
    expect(homeTree()).toEqual(home);
  });

  it("1+2: works on a repo with hand-written config, keeps it intact, and round-trips", async () => {
    for (const [rel, content] of Object.entries(HAND_WRITTEN)) {
      mkdirSync(inProject(ws, rel, ".."), { recursive: true });
      writeFileSync(inProject(ws, rel), content);
    }
    const before = projectTree();
    expect((await kit(["init", "--profile", "dev", "--yes"])).code).toBe(0);

    const settings = JSON.parse(readFileSync(inProject(ws, ".claude/settings.json"), "utf8"));
    expect(settings.permissions).toEqual({ allow: ["Bash(npm test)"], deny: [] });
    expect(settings.model).toBe("sonnet");
    expect(settings.hooks.PreToolUse[0].hooks[0].command).toBe("echo mine");
    expect(Object.keys(JSON.parse(readFileSync(inProject(ws, ".mcp.json"), "utf8")).mcpServers)).toEqual(["mine", "alpha-mcp"]);
    expect(readFileSync(inProject(ws, "CLAUDE.md"), "utf8").startsWith("# My project\n\nHouse rules.\n")).toBe(true);

    await kit(["update", "--yes"]); // an update with nothing new must not disturb anything either
    expect((await kit(["remove", "alpha", "--yes"])).code).toBe(0);
    expect(projectTree()).toEqual(before);
  });

  it("2: applying the same install twice changes nothing", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const once = snapshotTree(ws.project, [".harness-kit/backup"]);
    const again = await kit(["init", "--profile", "dev", "--yes"]);
    expect(again.output).toContain("(no file changes)");
    expect(snapshotTree(ws.project, [".harness-kit/backup"])).toEqual(once);
  });

  it("4: a company catalog's profile can bundle a public module", async () => {
    const company = makeGitCatalog(FIXTURES.company);
    expect((await kit(["catalog", "add", company])).code).toBe(0);
    const r = await kit(["init", "--profile", "industrial", "--yes"]);
    expect(r.code).toBe(0);
    const lock = JSON.parse(readFileSync(inProject(ws, ".harness-kit/lock.json"), "utf8"));
    expect(Object.keys(lock.modules).sort()).toEqual(["alpha", "gamma"]);
    expect(Object.keys(lock.catalogs).sort()).toEqual(["company", "public"]);
    const claudeMd = readFileSync(inProject(ws, "CLAUDE.md"), "utf8");
    expect(claudeMd).toContain("<!-- kit:alpha:start -->");
    expect(claudeMd).toContain("Company rules apply.");
  });

  it("a teammate's clone needs no user config: the project lock names its catalogs", async () => {
    await kit(["init", "--profile", "dev", "--yes"]);
    const teammate = { cwd: ws.project, home: tempDir("kit-teammate-") };
    expect((await runKit(["status"], teammate)).output).not.toContain("no catalogs");
    expect((await runKit(["add", "beta", "--scope", "project", "--yes"], teammate)).code).toBe(0);
  });
});
