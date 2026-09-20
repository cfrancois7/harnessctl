import { describe, expect, it } from "vitest";
import { lineDiff } from "../src/diff.js";

describe("lineDiff", () => {
  it("reports only changed lines, in order", () => {
    expect(lineDiff("a\nb\nc\n", "a\nB\nc\nd\n")).toEqual(["- b", "+ B", "+ d"]);
  });
  it("is empty for identical input", () => {
    expect(lineDiff("same\n", "same\n")).toEqual([]);
  });
});
