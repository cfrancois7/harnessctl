import { describe, expect, it } from "vitest";
import { KitError } from "../src/errors.js";
import { hashContent } from "../src/hash.js";
import { knownPlaceholders, listPlaceholders, renderTemplate, templateVars } from "../src/template.js";

describe("renderTemplate", () => {
  it("substitutes known placeholders, with or without inner spaces", () => {
    const out = renderTemplate("Hi {{config.greeting}} from {{ module.name }}", {
      "config.greeting": "hello", "module.name": "alpha",
    }, "alpha/instructions/a.md");
    expect(out).toBe("Hi hello from alpha");
  });

  it("throws KitError naming the file and placeholder when unknown", () => {
    expect(() => renderTemplate("{{config.nope}}", {}, "alpha/x.md"))
      .toThrowError(new KitError("alpha/x.md: unknown placeholder {{config.nope}}"));
  });

  it("leaves single-brace ${VAR} and { json } untouched", () => {
    expect(renderTemplate('{"a": "${TOKEN}"}', {}, "f")).toBe('{"a": "${TOKEN}"}');
  });
});

describe("template helpers", () => {
  it("lists unique placeholders", () => {
    expect(listPlaceholders("{{a.b}} {{a.b}} {{c}}")).toEqual(["a.b", "c"]);
  });

  it("builds vars from manifest and config; arrays join with ', '", () => {
    expect(templateVars({ name: "alpha", version: "1.0.0" }, { greeting: "hi", areas: ["api", "fw"], n: 3 }))
      .toEqual({ "module.name": "alpha", "module.version": "1.0.0",
                 "config.greeting": "hi", "config.areas": "api, fw", "config.n": "3" });
  });

  it("knows which placeholders a manifest allows", () => {
    expect(knownPlaceholders({ config: { greeting: {} } }))
      .toEqual(["module.name", "module.version", "config.greeting"]);
  });
});

describe("hashContent", () => {
  it("is a prefixed sha256 hex digest", () => {
    expect(hashContent("")).toBe("sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });
});
