import { describe, expect, it } from "vitest";
import { hasBlock, removeBlock, upsertBlock } from "../src/ops/marked-block.js";

const BLOCK = "<!-- kit:alpha:start -->\nhello\n<!-- kit:alpha:end -->\n";

describe("marked blocks", () => {
  it("creates the block in an empty file", () => {
    expect(upsertBlock("", "alpha", "hello\n")).toBe(BLOCK);
  });

  it("appends after a blank line and round-trips", () => {
    const original = "# Project\n\nRules.\n";
    const withBlock = upsertBlock(original, "alpha", "hello");
    expect(withBlock).toBe(original + "\n" + BLOCK);
    expect(removeBlock(withBlock, "alpha")).toBe(original);
  });

  it("round-trips a file that already ends with a blank line", () => {
    const original = "# Project\n\n";
    expect(removeBlock(upsertBlock(original, "alpha", "hello"), "alpha")).toBe(original);
  });

  it("replaces content in place, leaving surrounding text and other blocks alone", () => {
    const text = "top\n\n" + BLOCK + "\n<!-- kit:beta:start -->\nb\n<!-- kit:beta:end -->\nbottom\n";
    const updated = upsertBlock(text, "alpha", "changed");
    expect(updated).toBe(text.replace("hello", "changed"));
    expect(upsertBlock(updated, "alpha", "changed")).toBe(updated);
  });

  it("removes only its own block", () => {
    const text = upsertBlock(upsertBlock("top\n", "alpha", "a"), "beta", "b");
    const removed = removeBlock(text, "alpha");
    expect(hasBlock(removed, "alpha")).toBe(false);
    expect(hasBlock(removed, "beta")).toBe(true);
    expect(removeBlock(removed, "beta")).toBe("top\n");
  });

  it("is a no-op when the block is absent", () => {
    expect(removeBlock("text\n", "alpha")).toBe("text\n");
  });

  it("refuses an unterminated block", () => {
    expect(() => upsertBlock("<!-- kit:alpha:start -->\noops\n", "alpha", "x"))
      .toThrowError(/kit:alpha.*no end marker/);
  });
});
