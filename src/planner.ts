import type { AdapterEnv, HarnessAdapter } from "./adapters/adapter.js";
import { KitError } from "./errors.js";
import { fromPointer, toPointer } from "./ops/json-merge.js";
import { configValueProblem } from "./schema.js";
import type {
  Capability, HookEvent, Lockfile, ModuleDef, ModuleManifest, Operation, OwnedJson, Scope,
} from "./types.js";

const EVENT_CAPABILITY: Record<HookEvent, Capability> = {
  "pre-tool-use": "pre-tool-hook", "post-tool-use": "post-tool-hook",
  "session-start": "session-hook", "stop": "session-hook",
  "user-prompt": "user-prompt-hook", "subagent-start": "subagent-intercept",
};

export function impliedCapabilities(def: ModuleManifest): Capability[] {
  const caps = new Set<Capability>();
  if (def.contributes.skills.length > 0) caps.add("skills");
  if (def.contributes.instructions.length > 0) caps.add("instructions");
  if (Object.keys(def.contributes.mcpServers).length > 0) caps.add("mcp");
  for (const hook of def.contributes.hooks) {
    caps.add(EVENT_CAPABILITY[hook.event]);
    if (hook.match?.tool === "subagent") caps.add("subagent-intercept");
  }
  return [...caps];
}

export function supportStatus(
  def: ModuleManifest, adapter: HarnessAdapter,
): { status: "supported" | "degraded" | "unsupported"; missing: Capability[] } {
  const available = new Set(adapter.capabilities());
  const lacking = (caps: Capability[]) => [...new Set(caps)].filter((c) => !available.has(c)).sort();
  const required = lacking([...def.requires.capabilities, ...impliedCapabilities(def)]);
  if (required.length > 0) return { status: "unsupported", missing: required };
  const optional = lacking(def.requires.optional);
  return optional.length > 0 ? { status: "degraded", missing: optional } : { status: "supported", missing: [] };
}

export function resolveConfig(def: ModuleManifest, provided: Record<string, unknown>): Record<string, unknown> {
  for (const key of Object.keys(provided)) {
    if (!(key in def.config)) throw new KitError(`${def.name}: unknown config "${key}"`);
  }
  const resolved: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(def.config)) {
    const value = provided[key] ?? field.default;
    if (value === undefined) throw new KitError(`${def.name}: config "${key}" has no value`);
    const problem = configValueProblem(key, field, value);
    if (problem) throw new KitError(`${def.name}: ${problem}`);
    resolved[key] = value;
  }
  return resolved;
}

export interface Selection { def: ModuleDef; config: Record<string, unknown> }

function ownedHash(lock: Lockfile, target: string): string | undefined {
  for (const entry of Object.values(lock.modules)) {
    const hit = entry.owned.files.find((f) => f.path === target);
    if (hit) return hit.hash;
  }
  return undefined;
}

const ownedByOthers = (lock: Lockfile, names: string[], target: string): boolean =>
  Object.entries(lock.modules).some(([other, entry]) =>
    !names.includes(other) && entry.owned.files.some((f) => f.path === target));

const jsonKey = (file: string, pointer: string, match?: { commandContains: string }): string =>
  `${file} ${pointer} ${match?.commandContains ?? ""}`;

const removeJsonOp = (module: string, entry: OwnedJson): Operation => ({
  kind: "removeJson", module, target: entry.file, path: fromPointer(entry.pointer),
  ...(entry.match ? { match: entry.match } : {}),
});

export function planModule(
  selection: Selection, scope: Scope, adapter: HarnessAdapter, env: AdapterEnv, lock: Lockfile,
): Operation[] {
  const { def } = selection;
  if (!def.scopes.includes(scope)) {
    throw new KitError(`module "${def.name}" does not support ${scope} scope (supports: ${def.scopes.join(", ")})`);
  }
  const support = supportStatus(def, adapter);
  if (support.status === "unsupported") {
    throw new KitError(`module "${def.name}" needs capabilities that ${adapter.id} lacks: ${support.missing.join(", ")}`);
  }

  const forward = adapter.translate(def, resolveConfig(def, selection.config), scope, env).map((op) => {
    if (op.kind !== "writeOwned") return op;
    const expectedHash = ownedHash(lock, op.target);
    return expectedHash === undefined ? op : { ...op, expectedHash };
  });

  const previous = lock.modules[def.name];
  if (!previous) return forward;

  const files = new Set(forward.filter((o) => o.kind === "writeOwned").map((o) => o.target));
  const json = new Set(forward.flatMap((o) => (o.kind === "mergeJson" ? [jsonKey(o.target, toPointer(o.path), o.match)] : [])));
  const blocks = new Set(forward.flatMap((o) => (o.kind === "markedBlock" ? [`${o.target} ${o.id}`] : [])));

  const stale: Operation[] = [];
  for (const f of previous.owned.files) {
    if (!files.has(f.path) && !ownedByOthers(lock, [def.name], f.path)) {
      stale.push({ kind: "deleteOwned", module: def.name, target: f.path, expectedHash: f.hash });
    }
  }
  for (const j of previous.owned.json) {
    if (!json.has(jsonKey(j.file, j.pointer, j.match))) stale.push(removeJsonOp(def.name, j));
  }
  for (const b of previous.owned.blocks) {
    if (!blocks.has(`${b.file} ${b.id}`)) stale.push({ kind: "removeBlock", module: def.name, target: b.file, id: b.id });
  }
  return [...stale, ...forward];
}

export function planRemove(names: string[], lock: Lockfile): Operation[] {
  const ops: Operation[] = [];
  const deleted = new Set<string>();
  for (const name of names) {
    const entry = lock.modules[name];
    if (!entry) throw new KitError(`module "${name}" is not installed`);
    for (const f of entry.owned.files) {
      if (deleted.has(f.path) || ownedByOthers(lock, names, f.path)) continue;
      deleted.add(f.path);
      ops.push({ kind: "deleteOwned", module: name, target: f.path, expectedHash: f.hash });
    }
    for (const j of entry.owned.json) ops.push(removeJsonOp(name, j));
    for (const b of entry.owned.blocks) ops.push({ kind: "removeBlock", module: name, target: b.file, id: b.id });
  }
  return ops;
}
