import { KitError } from "../errors.js";
import type { Capability, ModuleDef, Operation, Scope } from "../types.js";
import { claudeCodeAdapter } from "./claude-code.js";

export interface AdapterEnv { home: string }

export interface HarnessAdapter {
  id: string;
  capabilities(): Capability[];
  /** Relative prefixes the executor may write to. "" = whole root, "dir/" = subtree, otherwise an exact file. */
  allowedPrefixes(scope: Scope): string[];
  /** Pure: turns a module into operations. `config` is already validated and defaulted. */
  translate(def: ModuleDef, config: Record<string, unknown>, scope: Scope, env: AdapterEnv): Operation[];
}

const ADAPTERS: Record<string, HarnessAdapter> = { "claude-code": claudeCodeAdapter };

export function getAdapter(id: string): HarnessAdapter {
  const adapter = ADAPTERS[id];
  if (!adapter) throw new KitError(`unknown harness "${id}"; available: ${Object.keys(ADAPTERS).join(", ")}`);
  return adapter;
}
