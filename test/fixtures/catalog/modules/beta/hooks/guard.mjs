import { run } from "../../runtime.mjs";

run(({ config, ask, deny }) =>
  config.mode === "block" ? deny("beta: sub-agents blocked") : ask("beta: confirm sub-agent"));
