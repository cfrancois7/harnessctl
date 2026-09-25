export const BlockSecretsRead = async () => ({
  "tool.execute.before": async (input: { tool: string }, output: { args: { filePath?: string } }) => {
    const path = output.args.filePath ?? ""
    if (["read", "grep"].includes(input.tool) && /(\.env$|\.pem$|secrets\/)/.test(path)) {
      throw new Error("blocked: secrets are off limits")
    }
  },
})
