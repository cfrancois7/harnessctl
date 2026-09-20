import { homedir } from "node:os";
import { parseArgs } from "node:util";
import { addCommand } from "./commands/add.js";
import { catalogCommand } from "./commands/catalog.js";
import { configCommand } from "./commands/config.js";
import { initCommand } from "./commands/init.js";
import { removeCommand } from "./commands/remove.js";
import { updateCommand } from "./commands/update.js";
import { validateCommand } from "./commands/validate.js";
import type { Command, Env } from "./env.js";
import { KitError } from "./errors.js";
import { clackPrompter } from "./prompts.js";
import { SCOPES, type Scope } from "./types.js";

const COMMANDS: Record<string, Command> = {
  add: addCommand,
  catalog: catalogCommand,
  config: configCommand,
  init: initCommand,
  remove: removeCommand,
  update: updateCommand,
  validate: validateCommand,
};

export const USAGE = `Usage: kit <command> [options]

Commands:
  init [--profile P]           choose a profile and modules, then install them
  add <module…>                install modules
  remove <module…>             uninstall modules
  update [module…]             move installed modules to the latest catalog version
  config <module>              change a module's settings
  list                         show catalog modules and what is installed
  status                       report drift, outdated modules and missing env vars
  catalog list|add|remove      manage catalog sources
  validate <catalog-path>      lint a catalog (for catalog CI)

Options:
  --scope project|user   where to install or look (default: the module's first scope)
  --yes, -y              no prompts; keep your version of any file you edited
  --dry-run              show the plan, write nothing
  --offline              use cached catalogs only
  --catalog <git-url>    use an extra catalog for this run (repeatable)
  --ref R, --subdir D    branch/tag/commit and subdirectory for catalog add / --catalog
  --harness H            target harness (default: claude-code)
  --help, -h`;

export async function main(argv: string[], overrides: Partial<Omit<Env, "flags">> = {}): Promise<number> {
  const out = overrides.out ?? ((line: string) => console.log(line));
  try {
    const { values, positionals } = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        yes: { type: "boolean", short: "y" },
        "dry-run": { type: "boolean" },
        offline: { type: "boolean" },
        help: { type: "boolean", short: "h" },
        scope: { type: "string" },
        profile: { type: "string" },
        harness: { type: "string" },
        ref: { type: "string" },
        subdir: { type: "string" },
        catalog: { type: "string", multiple: true },
      },
    });
    const [name, ...args] = positionals;
    if (values.help || name === undefined) {
      out(USAGE);
      return 0;
    }
    const command = COMMANDS[name];
    if (!command) throw new KitError(`unknown command "${name}"\n\n${USAGE}`);
    if (values.scope !== undefined && !(SCOPES as readonly string[]).includes(values.scope)) {
      throw new KitError("--scope must be project or user");
    }
    const env: Env = {
      cwd: overrides.cwd ?? process.cwd(),
      home: overrides.home ?? process.env.HARNESS_KIT_HOME ?? homedir(),
      out,
      prompter: overrides.prompter ?? clackPrompter,
      flags: {
        yes: values.yes ?? false,
        dryRun: values["dry-run"] ?? false,
        offline: values.offline ?? false,
        harness: values.harness ?? "claude-code",
        scope: values.scope as Scope | undefined,
        profile: values.profile,
        ref: values.ref,
        subdir: values.subdir,
        catalog: values.catalog ?? [],
      },
    };
    return await command(args, env);
  } catch (err) {
    const parseError = err instanceof TypeError && String((err as { code?: string }).code).startsWith("ERR_PARSE_ARGS");
    if (err instanceof KitError || parseError) {
      out(`error: ${(err as Error).message}`);
      return 1;
    }
    throw err;
  }
}
