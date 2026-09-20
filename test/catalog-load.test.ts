import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findProfile, loadCatalog, resolveModule } from "../src/catalog/load.js";
import { KitError } from "../src/errors.js";

const PUBLIC = join(import.meta.dirname, "fixtures/catalog");
const COMPANY = join(import.meta.dirname, "fixtures/company-catalog");

describe("loadCatalog", () => {
  it("loads modules with their files and profiles", () => {
    const cat = loadCatalog(PUBLIC);
    expect(cat.name).toBe("public");
    expect(cat.invalid).toEqual([]);
    expect(cat.modules.map((m) => m.name)).toEqual(["alpha", "beta"]);
    const alpha = cat.modules[0]!;
    expect(alpha.catalog).toBe("public");
    expect(Object.keys(alpha.files).sort()).toEqual([
      "hooks/check.mjs", "hooks/start.mjs", "instructions/alpha.md", "module.json",
      "skills/alpha-skill/SKILL.md", "templates/docs/INDEX.md",
    ]);
    expect(cat.profiles[0]).toMatchObject({ name: "dev", catalog: "public" });
  });

  it("records invalid modules instead of throwing", () => {
    const dir = mkdtempSync(join(tmpdir(), "kit-cat-"));
    cpSync(PUBLIC, dir, { recursive: true });
    const manifest = join(dir, "modules/beta/module.json");
    const raw = JSON.parse(readFileSync(manifest, "utf8"));
    raw.contributes.hooks[0].run = "hooks/nope.mjs";
    writeFileSync(manifest, JSON.stringify(raw));
    const cat = loadCatalog(dir);
    expect(cat.modules.map((m) => m.name)).toEqual(["alpha"]);
    expect(cat.invalid).toEqual([{ name: "beta", problems: ["missing hook script hooks/nope.mjs"] }]);
  });

  it("throws when catalog.json is missing", () => {
    expect(() => loadCatalog(tmpdir())).toThrowError(KitError);
  });
});

describe("name resolution", () => {
  const catalogs = [loadCatalog(PUBLIC), loadCatalog(COMPANY)];

  it("resolves unqualified and qualified names across catalogs", () => {
    expect(resolveModule(catalogs, "gamma").catalog).toBe("company");
    expect(resolveModule(catalogs, "public:alpha").name).toBe("alpha");
  });

  it("explains unknown, ambiguous and invalid modules", () => {
    expect(() => resolveModule(catalogs, "nope")).toThrowError(/module "nope" not found/);
    const other = { ...catalogs[0]!, name: "other",
      modules: catalogs[0]!.modules.map((m) => ({ ...m, catalog: "other" })) };
    expect(() => resolveModule([catalogs[0]!, other], "alpha"))
      .toThrowError(/ambiguous.*public:alpha.*other:alpha/s);
    const broken = { ...catalogs[1]!, modules: [], invalid: [{ name: "gamma", problems: ["boom"] }] };
    expect(() => resolveModule([broken], "gamma")).toThrowError(/gamma.*invalid.*boom/s);
  });

  it("finds profiles in any catalog", () => {
    expect(findProfile(catalogs, "industrial").modules).toHaveProperty("alpha");
    expect(() => findProfile(catalogs, "nope")).toThrowError(/profile "nope" not found.*dev, industrial/s);
  });
});
