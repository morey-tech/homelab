// Credential-free protocol test. Pass a temporary npm install directory that
// contains mcp/package*.json, mcp/run-ynab.mjs, and its installed node_modules.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const runtime = path.resolve(process.argv[2]);
const sdk = path.join(runtime, "node_modules/@modelcontextprotocol/sdk/dist/esm");
const { Client } = await import(pathToFileURL(path.join(sdk, "client/index.js")));
const { StdioClientTransport } = await import(pathToFileURL(path.join(sdk, "client/stdio.js")));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "ynab-mcp-test-"));
const token = path.join(temporary, "token");
fs.writeFileSync(token, "fake-token-for-local-test\n", { mode: 0o600 });
const entry = path.join(temporary, "entry.mjs");
fs.writeFileSync(entry, `import { startServer } from ${JSON.stringify(pathToFileURL(path.join(runtime, "run-ynab.mjs")).href)};
import assert from "node:assert/strict";
// Exercise the real tool and SDK with a fake HTTP response; never use network.
globalThis.fetch = async (url, init) => {
  assert.equal(init.method, "GET");
  assert.equal(new Headers(init.headers).get("Authorization"), "Bearer fake-token-for-local-test");
  return new Response(JSON.stringify({ data: { plans: [{ id: "test-plan", name: "Local fixture" }] } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
await startServer(${JSON.stringify(token)});
`);

try {
  for (const readOnly of ["false", "true"]) {
    const client = new Client({ name: "ynab-local-validation", version: "1.0.0" });
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [entry],
      env: { PATH: process.env.PATH, YNAB_READ_ONLY: readOnly },
      stderr: "inherit",
    });
    try {
      await client.connect(transport);
      await client.ping();
      const { tools } = await client.listTools();
      const names = tools.map(tool => tool.name);
      assert.ok(names.includes("ynab_list_plans"));
      assert.ok(names.includes("ynab_get_transactions"));
      assert.ok(!names.includes("ynab_suggest_categories"));
      assert.equal(names.includes("ynab_create_transaction"), readOnly === "false");
      assert.equal(names.includes("ynab_delete_transaction"), readOnly === "false");
      assert.equal(names.includes("ynab_update_category_budget"), readOnly === "false");
      assert.equal(tools.length, readOnly === "true" ? 14 : 24);
      if (readOnly === "true") assert.ok(tools.every(tool => tool.annotations.readOnlyHint));
      const result = await client.callTool({ name: "ynab_list_plans", arguments: {} });
      assert.ok(!result.isError, "List-plans tool must accept the mounted token");
      assert.deepEqual(JSON.parse(result.content[0].text), [{ id: "test-plan", name: "Local fixture" }]);
      console.log(`PASS: YNAB_READ_ONLY=${readOnly}: connected, pinged, discovered ${tools.length} tools, listed fixture plans`);
    } finally {
      await client.close();
    }
  }
  console.log("No external YNAB API calls made; HTTP responses were mocked.");
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
