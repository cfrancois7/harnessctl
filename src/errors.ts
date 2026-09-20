/** A failure the user can act on. main() prints the message and exits 1. */
export class KitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "KitError";
  }
}
