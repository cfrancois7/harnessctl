import type { Prompter } from "./prompts.js";
import type { Scope } from "./types.js";

export interface Flags {
  yes: boolean;
  dryRun: boolean;
  offline: boolean;
  harness: string;
  scope?: Scope;
  profile?: string;
  ref?: string;
  subdir?: string;
  catalog: string[];
}

export interface Env {
  cwd: string;
  home: string;
  out: (line: string) => void;
  prompter: Prompter;
  flags: Flags;
}

/** Returns the process exit code. */
export type Command = (args: string[], env: Env) => Promise<number>;
