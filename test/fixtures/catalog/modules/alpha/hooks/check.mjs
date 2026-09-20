import { run } from "../../runtime.mjs";

run(({ tool, config, allow, deny }) => {
  const command = String(tool.input?.command ?? "");
  if (command.includes("alpha-deny-me")) return deny(`alpha (${config.greeting}) blocked this command`);
  return allow();
});
