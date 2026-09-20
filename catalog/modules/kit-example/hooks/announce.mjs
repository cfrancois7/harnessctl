import { run } from "../../runtime.mjs";

run(({ config, warn }) => warn(`kit-example is active: ${config.greeting}`));
