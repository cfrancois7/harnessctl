export const SCOPES = ["project", "user"] as const;
export type Scope = (typeof SCOPES)[number];

export const CAPABILITIES = [
  "skills", "instructions", "mcp",
  "pre-tool-hook", "post-tool-hook", "session-hook", "user-prompt-hook",
  "subagent-intercept", "usage-telemetry", "statusline",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const HOOK_EVENTS = [
  "pre-tool-use", "post-tool-use", "session-start", "user-prompt", "subagent-start", "stop",
] as const;
export type HookEvent = (typeof HOOK_EVENTS)[number];

export const TOOL_MATCHERS = ["*", "subagent", "shell", "edit"] as const;
export type ToolMatcher = (typeof TOOL_MATCHERS)[number];

export const CONFIG_TYPES = ["string", "number", "boolean", "enum", "string[]"] as const;
export type ConfigType = (typeof CONFIG_TYPES)[number];

export interface ConfigField {
  type: ConfigType;
  default?: unknown;
  prompt?: string;
  values?: string[];
}

export interface HookContribution {
  event: HookEvent;
  match?: { tool: ToolMatcher };
  /** Path inside the module, always under `hooks/`. */
  run: string;
  onError: "allow" | "deny";
}

export interface ScaffoldContribution { from: string; to: string }

/** module.json after validation and defaulting. */
export interface ModuleManifest {
  name: string;
  version: string;
  description: string;
  scopes: Scope[];
  requires: { capabilities: Capability[]; optional: Capability[]; env: string[] };
  config: Record<string, ConfigField>;
  contributes: {
    skills: string[];
    hooks: HookContribution[];
    instructions: string[];
    mcpServers: Record<string, unknown>;
    scaffold: ScaffoldContribution[];
  };
}

/** A manifest plus everything needed to install it without touching disk again. */
export interface ModuleDef extends ModuleManifest {
  /** Name of the catalog this module came from. */
  catalog: string;
  /** Every file in the module folder: POSIX relative path -> UTF-8 content. */
  files: Record<string, string>;
}

export interface ProfileEntry { scope?: Scope; config?: Record<string, unknown> }
export interface Profile {
  name: string;
  description: string;
  modules: Record<string, ProfileEntry>;
  catalog: string;
}

export interface ArrayMatch { commandContains: string }

export type Operation =
  | { kind: "writeOwned"; module: string; target: string; content: string; expectedHash?: string }
  | { kind: "scaffoldOnce"; module: string; target: string; content: string }
  /**
   * `owned` marks a key-addressed (match-less) entry the lock already records this module as
   * owning: the executor may then replace it without asking. Set by the planner, never by an
   * adapter. Entries addressed with `match` are kit-owned by construction.
   */
  | { kind: "mergeJson"; module: string; target: string; path: string[]; value: unknown; match?: ArrayMatch; owned?: boolean }
  | { kind: "markedBlock"; module: string; target: string; id: string; content: string }
  | { kind: "deleteOwned"; module: string; target: string; expectedHash: string }
  | { kind: "removeJson"; module: string; target: string; path: string[]; match?: ArrayMatch }
  | { kind: "removeBlock"; module: string; target: string; id: string };

export interface OwnedFile { path: string; hash: string }
export interface OwnedJson { file: string; pointer: string; match?: ArrayMatch }
export interface OwnedBlock { file: string; id: string }
export interface Owned { files: OwnedFile[]; json: OwnedJson[]; blocks: OwnedBlock[] }

export interface CatalogSource { url: string; ref?: string; subdir?: string }
export interface CatalogLock extends CatalogSource { sha: string }

export interface ModuleLock {
  catalog: string;
  version: string;
  config: Record<string, unknown>;
  owned: Owned;
  scaffolded: string[];
}

export interface Lockfile {
  lockVersion: 1;
  harness: string;
  profile?: string;
  catalogs: Record<string, CatalogLock>;
  /** Files the kit created through mergeJson/markedBlock; deleted again once blank. */
  createdFiles: string[];
  modules: Record<string, ModuleLock>;
}
