import { KitError } from "../errors.js";

const startMarker = (id: string) => `<!-- kit:${id}:start -->`;
const endMarker = (id: string) => `<!-- kit:${id}:end -->`;

function findBlock(text: string, id: string): { start: number; end: number } | null {
  const start = text.indexOf(startMarker(id));
  if (start < 0) return null;
  const endAt = text.indexOf(endMarker(id), start);
  if (endAt < 0) throw new KitError(`block kit:${id} has a start marker but no end marker`);
  let end = endAt + endMarker(id).length;
  if (text[end] === "\n") end += 1;
  return { start, end };
}

export function hasBlock(text: string, id: string): boolean {
  return findBlock(text, id) !== null;
}

export function upsertBlock(text: string, id: string, content: string): string {
  const block = `${startMarker(id)}\n${content.trim()}\n${endMarker(id)}\n`;
  const range = findBlock(text, id);
  if (range) return text.slice(0, range.start) + block + text.slice(range.end);
  if (text === "") return block;
  return text + (text.endsWith("\n") ? "\n" : "\n\n") + block;
}

export function removeBlock(text: string, id: string): string {
  const range = findBlock(text, id);
  if (!range) return text;
  let start = range.start;
  // upsertBlock separated the block with one blank line; take that separator back out.
  if (text.slice(0, start).endsWith("\n\n")) start -= 1;
  return text.slice(0, start) + text.slice(range.end);
}
