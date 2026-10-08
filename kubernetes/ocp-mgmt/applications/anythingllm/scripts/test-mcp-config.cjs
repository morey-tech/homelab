const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { configure } = require("../mcp/configure.cjs");

const source = path.resolve(__dirname, "../mcp/anythingllm_mcp_servers.json");

test("bootstrap storage, preserve existing MCP servers and data, and reconcile YNAB", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anythingllm-mcp-"));
  try {
    const storage = path.join(root, "storage");
    configure(storage, source);
    const destination = path.join(storage, "plugins/anythingllm_mcp_servers.json");
    const config = JSON.parse(fs.readFileSync(destination, "utf8"));
    assert.equal(config.mcpServers.ynab.env.YNAB_READ_ONLY, "true");
    assert.equal(config.mcpServers.ynab.command, "/opt/ynab-mcp/node");
    for (const directory of ["documents", "vector-cache", "lancedb", "plugins/agent-skills"]) {
      assert.ok(fs.statSync(path.join(storage, directory)).isDirectory());
    }
    config.mcpServers.existing = { command: "existing", env: { EXAMPLE: "preserve" } };
    config.extra = { preserve: true };
    config.mcpServers.ynab = { command: "stale" };
    fs.writeFileSync(destination, JSON.stringify(config));
    const database = path.join(storage, "anythingllm.db");
    fs.writeFileSync(database, "existing database content");
    configure(storage, source);
    const updated = JSON.parse(fs.readFileSync(destination, "utf8"));
    assert.deepEqual(updated.mcpServers.existing, config.mcpServers.existing);
    assert.deepEqual(updated.extra, config.extra);
    assert.equal(updated.mcpServers.ynab.command, "/opt/ynab-mcp/node");
    assert.equal(fs.readFileSync(database, "utf8"), "existing database content");
    const once = fs.readFileSync(destination, "utf8");
    configure(storage, source);
    assert.equal(fs.readFileSync(destination, "utf8"), once);
    assert.equal(fs.statSync(destination).mode & 0o777, 0o600);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("reject invalid saved configurations without overwriting them", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anythingllm-mcp-"));
  try {
    fs.mkdirSync(path.join(root, "plugins"));
    const destination = path.join(root, "plugins/anythingllm_mcp_servers.json");
    for (const invalid of ["{broken", "null", "{}", '{"mcpServers":[]}', '{"mcpServers":null}']) {
      fs.writeFileSync(destination, invalid);
      assert.throws(() => configure(root, source));
      assert.equal(fs.readFileSync(destination, "utf8"), invalid);
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
