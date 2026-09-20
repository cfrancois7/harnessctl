import { run } from "../../runtime.mjs";

run(({ config, warn }) => warn(`alpha active: ${config.greeting}`));
