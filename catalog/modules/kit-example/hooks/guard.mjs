import { run } from "../../runtime.mjs";

run(({ tool, allow, deny }) => {
  const command = String(tool.input?.command ?? "");
  return command.includes("kit-example-deny-me")
    ? deny("kit-example blocked this command (it contains kit-example-deny-me)")
    : allow();
});
