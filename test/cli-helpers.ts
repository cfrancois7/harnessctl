import { join } from "node:path";
import { main } from "../src/cli.js";
import type { Choice, Prompter } from "../src/prompts.js";
import { writeUserConfig } from "../src/userconfig.js";
import { FIXTURES, git, makeGitCatalog, tempDir } from "./helpers.js";

export interface Answers { select?: unknown[]; multiselect?: unknown[][]; text?: string[]; confirm?: boolean[] }

export function fakePrompter(answers: Answers): Prompter & { asked: string[] } {
  const queues = {
    select: [...(answers.select ?? [])], multiselect: [...(answers.multiselect ?? [])],
    text: [...(answers.text ?? [])], confirm: [...(answers.confirm ?? [])],
  };
  const asked: string[] = [];
  return {
    asked,
    async select<T>(message: string, choices: Choice<T>[], initial?: T) {
      asked.push(message);
      return (queues.select.length > 0 ? queues.select.shift() : initial ?? choices[0]!.value) as T;
    },
    async multiselect<T>(message: string, _choices: Choice<T>[], initial: T[]) {
      asked.push(message);
      return (queues.multiselect.length > 0 ? queues.multiselect.shift() : initial) as T[];
    },
    async text(message: string, initial?: string) {
      asked.push(message);
      return queues.text.length > 0 ? queues.text.shift()! : initial ?? "";
    },
    async confirm(message: string, initial?: boolean) {
      asked.push(message);
      return queues.confirm.length > 0 ? queues.confirm.shift()! : initial ?? true;
    },
  };
}

export async function runKit(
  args: string[], ctx: { cwd: string; home: string; answers?: Answers },
): Promise<{ code: number; output: string; asked: string[] }> {
  const lines: string[] = [];
  const prompter = fakePrompter(ctx.answers ?? {});
  const code = await main(args, { cwd: ctx.cwd, home: ctx.home, out: (line) => lines.push(line), prompter });
  return { code, output: lines.join("\n"), asked: prompter.asked };
}

export interface Workspace { home: string; project: string; publicRepo: string }

export function makeWorkspace(): Workspace {
  const home = tempDir("kit-home-");
  const project = tempDir("kit-project-");
  git(project, "init", "--quiet", "-b", "main");
  const publicRepo = makeGitCatalog(FIXTURES.public);
  writeUserConfig(home, { catalogs: [{ url: publicRepo }] });
  return { home, project, publicRepo };
}

export const inProject = (ws: Workspace, ...parts: string[]): string => join(ws.project, ...parts);
export const inHome = (ws: Workspace, ...parts: string[]): string => join(ws.home, ...parts);
