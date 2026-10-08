import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { API } from "ynab";
import { registerAll } from "ynab-mcp-server/dist/registry.js";

export async function startServer(tokenPath = "/var/run/secrets/ynab/YNAB_API_TOKEN") {
  // Read the projected Secret on each MCP start, including after rotation.
  // Keep the token out of the persisted MCP JSON and process environments.
  const token = fs.readFileSync(tokenPath, "utf8").trim();
  if (!token) throw new Error("YNAB_API_TOKEN is empty");
  const server = new McpServer({ name: "ynab-mcp-server", version: "0.4.1" });
  // Upstream 0.4.1's stdio entry point does not pass the readOnly option.
  // Its registry supports it; default to read-only unless explicitly disabled.
  registerAll(server, new API(token), {
    readOnly: process.env.YNAB_READ_ONLY !== "false",
  });
  await server.connect(new StdioServerTransport());
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startServer().catch(() => {
    // Do not log exception contents, which could include credential material.
    console.error("YNAB MCP failed to start; check the token Secret and installed runtime.");
    process.exitCode = 1;
  });
}
