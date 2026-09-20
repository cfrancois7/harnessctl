import {
  applyEdits, findNodeAtLocation, format, modify, parse, parseTree,
  type FormattingOptions, type ModificationOptions, type ParseError,
} from "jsonc-parser";
import { KitError } from "../errors.js";
import type { ArrayMatch } from "../types.js";

type Path = (string | number)[];

function detectFormat(text: string): FormattingOptions {
  const indent = text.match(/\n([ \t]+)\S/)?.[1] ?? "  ";
  const tabs = indent.includes("\t");
  return { insertSpaces: !tabs, tabSize: tabs ? 1 : indent.length, eol: text.includes("\r\n") ? "\r\n" : "\n" };
}

function parseObject(text: string, file: string): Record<string, unknown> {
  const errors: ParseError[] = [];
  const value: unknown = parse(text, errors, { allowTrailingComma: true });
  if (errors.length > 0 || value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new KitError(`cannot parse ${file}: not a valid JSON object`);
  }
  return value as Record<string, unknown>;
}

function getAt(root: unknown, path: Path): unknown {
  let current = root;
  for (const segment of path) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string | number, unknown>)[segment];
  }
  return current;
}

const isEmptyContainer = (v: unknown): boolean =>
  v !== null && typeof v === "object" && Object.keys(v as object).length === 0;

const entryMatches = (entry: unknown, match: ArrayMatch): boolean =>
  JSON.stringify(entry).includes(match.commandContains);

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

/** Set a value. Only the inserted range is formatted, so neighbouring text keeps its bytes. */
function setAt(src: string, file: string, path: Path, value: unknown, options: ModificationOptions = {}): string {
  const formattingOptions = detectFormat(src);
  if (isEmptyContainer(parseObject(src, file))) {
    return applyEdits(src, modify(src, path, value, { ...options, formattingOptions }));
  }
  const edits = modify(src, path, value, options);
  if (edits.length === 0) return src;
  const raw = applyEdits(src, edits);
  const inserted = { offset: edits[0]!.offset, length: edits[0]!.content.length };
  return applyEdits(raw, format(raw, inserted, formattingOptions));
}

/** Remove a node by offsets: exactly the text an insertion added, including its separator. */
function deleteAt(src: string, path: Path): string {
  const tree = parseTree(src);
  const valueNode = tree ? findNodeAtLocation(tree, path) : undefined;
  if (!valueNode?.parent) return src;
  const node = valueNode.parent.type === "property" ? valueNode.parent : valueNode;
  const container = node.parent;
  const siblings = container?.children;
  if (!container || !siblings) return src;
  const index = siblings.indexOf(node);
  let start: number;
  let end: number;
  if (index > 0) {
    const previous = siblings[index - 1]!;
    start = previous.offset + previous.length;
    end = node.offset + node.length;
  } else if (siblings.length > 1) {
    start = node.offset;
    end = siblings[1]!.offset;
  } else {
    start = container.offset + 1;
    end = container.offset + container.length - 1;
  }
  return src.slice(0, start) + src.slice(end);
}

function arrayAt(root: unknown, file: string, path: string[]): unknown[] | undefined {
  const value = getAt(root, path);
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new KitError(`${file}: ${toPointer(path)} is not an array`);
  return value;
}

export function upsertJsonEntry(text: string, file: string, path: string[], value: unknown, match?: ArrayMatch): string {
  const src = text.trim() === "" ? "{}" : text;
  const root = parseObject(src, file);
  if (!match) return same(getAt(root, path), value) ? src : setAt(src, file, path, value);
  const array = arrayAt(root, file, path);
  if (array === undefined) return setAt(src, file, path, [value]);
  const index = array.findIndex((entry) => entryMatches(entry, match));
  if (index >= 0) return same(array[index], value) ? src : setAt(src, file, [...path, index], value);
  return setAt(src, file, [...path, array.length], value, { isArrayInsertion: true });
}

export function removeJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): string {
  if (text.trim() === "") return text;
  const root = parseObject(text, file);
  let target: Path = path;
  if (match) {
    const index = (arrayAt(root, file, path) ?? []).findIndex((entry) => entryMatches(entry, match));
    if (index < 0) return text;
    target = [...path, index];
  } else if (getAt(root, path) === undefined) {
    return text;
  }
  let src = deleteAt(text, target);
  let parent = target.slice(0, -1);
  while (parent.length > 0 && isEmptyContainer(getAt(parseObject(src, file), parent))) {
    src = deleteAt(src, parent);
    parent = parent.slice(0, -1);
  }
  return src;
}

export function hasJsonEntry(text: string, file: string, path: string[], match?: ArrayMatch): boolean {
  if (text.trim() === "") return false;
  const root = parseObject(text, file);
  if (!match) return getAt(root, path) !== undefined;
  return (arrayAt(root, file, path) ?? []).some((entry) => entryMatches(entry, match));
}

export function isEmptyJson(text: string): boolean {
  if (/\/\/|\/\*/.test(text)) return false;
  try {
    return isEmptyContainer(parseObject(text.trim() === "" ? "{}" : text, ""));
  } catch {
    return false;
  }
}

export function toPointer(path: string[]): string {
  return path.map((s) => "/" + s.replace(/~/g, "~0").replace(/\//g, "~1")).join("");
}

export function fromPointer(pointer: string): string[] {
  return pointer.split("/").slice(1).map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
}
