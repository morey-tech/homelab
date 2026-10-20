import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

async function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'openclaw-test-'));
  const keyPath = join(dir, 'key');
  writeFileSync(keyPath, 'test-key-one');
  const code = `import {launch} from ${JSON.stringify(new URL('./launch.mjs', import.meta.url).href)};
    launch({keyPath:${JSON.stringify(keyPath)}, intervalMs:20, graceMs:300,
      args:['-e', 'if(process.env.MAAS_API_KEY!=="test-key-one")process.exit(9); console.log("READY");setInterval(()=>{},1000)']});`;
  const child = spawn(process.execPath, ['--input-type=module', '-e', code], { stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  let errors = '';
  child.stderr.on('data', b => { errors += b; });
  const started = Date.now();
  child.stdout.on('data', b => { output += b; });
  const done = once(child, 'exit');
  t.after(() => { child.kill('SIGKILL'); rmSync(dir, { recursive: true, force: true }); });
  while (!output.includes('READY')) {
    if (child.exitCode !== null || child.signalCode || Date.now()-started > 2000) throw new Error('Launcher failed before ready: '+errors+output);
    await new Promise(r => setTimeout(r, 10));
  }
  return {child, keyPath, done, output:()=>output};
}

test('credential change stops gateway without logging credentials', {timeout:5000}, async t => {
  const f = await fixture(t);
  writeFileSync(f.keyPath, 'test-key-two');
  const [code] = await f.done;
  assert.equal(code, 0);
  assert.match(f.output(), /credential changed/);
  assert.doesNotMatch(f.output(), /test-key/);
});
test('empty projection retains gateway and SIGTERM shuts it down', {timeout:5000}, async t => {
  const f = await fixture(t);
  writeFileSync(f.keyPath, '');
  await new Promise(r => setTimeout(r, 100));
  assert.equal(f.child.exitCode, null);
  f.child.kill('SIGTERM');
  assert.equal((await f.done)[0], 0);
});
test('missing projection retains gateway', {timeout:5000}, async t => {
  const f = await fixture(t);
  rmSync(f.keyPath);
  await new Promise(r => setTimeout(r, 100));
  assert.equal(f.child.exitCode, null);
  f.child.kill('SIGTERM');
  assert.equal((await f.done)[0], 0);
});
