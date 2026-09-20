import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { KitError } from "../errors.js";
import type { CatalogSource } from "../types.js";

export interface FetchedCatalog { source: CatalogSource; dir: string; sha: string }

function git(args: string[], cwd?: string): string {
  try {
    return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  } catch (err) {
    const e = err as { stderr?: string; message: string };
    throw new KitError(`git ${args[0]} failed: ${(e.stderr || e.message).trim()}`);
  }
}

function resolveRef(clone: string, source: CatalogSource): string {
  const candidates = source.ref ? [`origin/${source.ref}`, source.ref] : ["origin/HEAD"];
  for (const candidate of candidates) {
    try {
      return git(["rev-parse", "--verify", "--quiet", `${candidate}^{commit}`], clone);
    } catch {
      // try the next spelling
    }
  }
  throw new KitError(`ref "${source.ref ?? "HEAD"}" not found in ${source.url}`);
}

export function fetchCatalog(
  source: CatalogSource, cacheRoot: string, options: { offline?: boolean; sha?: string } = {},
): FetchedCatalog {
  // Validate subdir to prevent path traversal
  if (source.subdir) {
    if (source.subdir.startsWith("/") || source.subdir.includes("\\")) {
      throw new KitError(`invalid catalog subdir "${source.subdir}": must be a relative path inside the repository`);
    }
    const segments = source.subdir.split("/");
    for (const segment of segments) {
      if (segment === "" || segment === "." || segment === "..") {
        throw new KitError(`invalid catalog subdir "${source.subdir}": must be a relative path inside the repository`);
      }
    }
  }

  // Validate sha to prevent git injection
  if (options.sha && !/^[0-9a-f]{7,40}$/.test(options.sha)) {
    throw new KitError(`invalid catalog sha "${options.sha}"`);
  }

  // Validate ref to prevent git injection
  if (source.ref && source.ref.startsWith("-")) {
    throw new KitError(`invalid catalog ref "${source.ref}"`);
  }

  const key = createHash("sha1").update(`${source.url}\n${source.ref ?? ""}`).digest("hex").slice(0, 16);
  const clone = join(cacheRoot, key);
  const cached = existsSync(join(clone, ".git"));

  if (options.offline) {
    if (!cached) throw new KitError(`catalog ${source.url} is not cached; run once without --offline`);
  } else if (!cached) {
    mkdirSync(cacheRoot, { recursive: true });
    git(["clone", "--quiet", "--", source.url, clone]);
  } else {
    git(["fetch", "--quiet", "--tags", "--prune", "origin"], clone);
  }

  git(["checkout", "--quiet", "--detach", options.sha ?? resolveRef(clone, source)], clone);
  const sha = git(["rev-parse", "HEAD"], clone);
  const dir = source.subdir ? join(clone, source.subdir) : clone;
  if (!existsSync(dir)) throw new KitError(`subdirectory "${source.subdir}" not found in ${source.url}`);
  return { source, dir, sha };
}
