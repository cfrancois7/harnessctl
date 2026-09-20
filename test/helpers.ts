import { mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** A fresh temp directory, realpath'd (on macOS /tmp is a symlink). */
export function tempDir(prefix = "kit-"): string {
  return realpathSync(mkdtempSync(join(tmpdir(), prefix)));
}
