const fs = require("node:fs");
const path = require("node:path");

function configure(storageDir, source) {
  const destination = path.join(storageDir, "plugins/anythingllm_mcp_servers.json");
  const config = fs.existsSync(destination)
    ? JSON.parse(fs.readFileSync(destination, "utf8"))
    : { mcpServers: {} };
  if (!config || typeof config !== "object" || Array.isArray(config) ||
      !config.mcpServers || typeof config.mcpServers !== "object" ||
      Array.isArray(config.mcpServers)) {
    throw new Error("Existing MCP configuration must contain a mcpServers object");
  }
  const managed = JSON.parse(fs.readFileSync(source, "utf8"));
  config.mcpServers.ynab = managed.mcpServers.ynab;

  // The workbench launcher creates these only when storage itself is absent.
  // Prepare the same layout because this init container creates storage first.
  for (const directory of ["documents", "vector-cache", "lancedb", "plugins/agent-skills"]) {
    fs.mkdirSync(path.join(storageDir, directory), { recursive: true });
  }
  fs.closeSync(fs.openSync(path.join(storageDir, "anythingllm.db"), "a"));

  // Preserve other server definitions and top-level settings; reject malformed
  // existing JSON instead of replacing it. The app retains a writable config.
  const temporary = `${destination}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, destination);
}

if (require.main === module) {
  configure(process.argv[2], process.argv[3]);
}
module.exports = { configure };
