import * as clack from "@clack/prompts";
import { KitError } from "./errors.js";
import type { ModuleManifest } from "./types.js";

export interface Choice<T> { value: T; label: string; hint?: string }

export interface Prompter {
  select<T>(message: string, choices: Choice<T>[], initial?: T): Promise<T>;
  multiselect<T>(message: string, choices: Choice<T>[], initial: T[]): Promise<T[]>;
  text(message: string, initial?: string, validate?: (value: string) => string | undefined): Promise<string>;
  confirm(message: string, initial?: boolean): Promise<boolean>;
}

function unwrap<T>(value: T | symbol): T {
  if (clack.isCancel(value)) throw new KitError("cancelled");
  return value as T;
}

// clack's option types are conditional on the value type; the casts keep our interface simple.
export const clackPrompter: Prompter = {
  async select<T>(message: string, choices: Choice<T>[], initial?: T) {
    return unwrap(await clack.select({ message, options: choices as never, initialValue: initial as never })) as T;
  },
  async multiselect<T>(message: string, choices: Choice<T>[], initial: T[]) {
    return unwrap(await clack.multiselect({
      message, options: choices as never, initialValues: initial as never, required: false })) as T[];
  },
  async text(message, initial, validate) {
    return unwrap<string>(await clack.text({ message, initialValue: initial, validate: validate as never }));
  },
  async confirm(message, initial) {
    return unwrap<boolean>(await clack.confirm({ message, initialValue: initial ?? true }));
  },
};

/** Ask every config question of a module, starting from `current` values, then manifest defaults. */
export async function promptConfig(
  def: ModuleManifest, current: Record<string, unknown>, prompter: Prompter,
): Promise<Record<string, unknown>> {
  const result: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(def.config)) {
    const message = `${def.name} › ${field.prompt ?? key}`;
    const start = current[key] ?? field.default;
    switch (field.type) {
      case "boolean":
        result[key] = await prompter.confirm(message, typeof start === "boolean" ? start : false);
        break;
      case "enum":
        result[key] = await prompter.select(message, (field.values ?? []).map((v) => ({ value: v, label: v })),
          typeof start === "string" ? start : undefined);
        break;
      case "number": {
        const answer = await prompter.text(message, start === undefined ? "" : String(start),
          (v) => (v.trim() !== "" && Number.isFinite(Number(v)) ? undefined : "Enter a number"));
        result[key] = Number(answer);
        break;
      }
      case "string[]": {
        const answer = await prompter.text(`${message} (comma-separated)`, Array.isArray(start) ? start.join(", ") : "");
        result[key] = answer.split(",").map((s) => s.trim()).filter((s) => s !== "");
        break;
      }
      case "string":
        result[key] = await prompter.text(message, typeof start === "string" ? start : "");
        break;
    }
  }
  return result;
}
