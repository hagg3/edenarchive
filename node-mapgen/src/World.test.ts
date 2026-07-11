// Regression tests for the chunk-table parsing/area-computation fixes found
// live against two real archive worlds that used to crash or hang
// node-mapgen (see the MAX_CHUNK_COUNT/MAX_CHUNK_AREA comment block in
// World.ts):
//   - 1770253120: a genuine ~6.3 GB world whose chunk-table scan produced
//     millions of spurious entries; Math.min(...xs) on that many args threw
//     "Maximum call stack size exceeded".
//   - 1315736126: a genuine ~20 MB, 626-chunk world with several spatially
//     separate builds; the naive min/max bounding box spanned all of them
//     (5912x5912 chunks), and allocating a canvas for that hung the process.
//
// Tests build synthetic .eden buffers (just enough header + chunk pointer
// table for loadWorldFromArrayBuffer to parse) rather than depending on the
// real archive files, so they run in milliseconds and don't need fixtures.
import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { loadWorldFromArrayBuffer, WorldParseError } from './World';

function buildEdenBuffer(chunks: { x: number; y: number; address?: number }[]): ArrayBuffer {
  const tableOffset = 200; // just past the 192-byte header
  // Every entry gets a distinct, small, positive address (well clear of the
  // table region) so the `address > 0 && address < bytes.length` validity
  // filter accepts all of them regardless of how many there are.
  const totalSize = tableOffset + chunks.length * 16 + 16;
  const buf = new ArrayBuffer(totalSize);
  const view = new DataView(buf);
  view.setUint32(32, tableOffset, true); // directory_offset (chunk pointer table start)

  let idx = tableOffset;
  chunks.forEach((c, i) => {
    view.setInt16(idx, c.x, true);
    view.setInt16(idx + 4, c.y, true);
    view.setUint32(idx + 8, c.address ?? 16 + i, true);
    idx += 16;
  });
  return buf;
}

test('a small, tightly-clustered world is unaffected (fast path, no trimming)', () => {
  const chunks = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 0, y: 1 },
    { x: 5, y: 5 },
  ];
  const world = loadWorldFromArrayBuffer(buildEdenBuffer(chunks));
  assert.equal(world.meta.chunks.length, 4);
  assert.equal(world.meta.worldArea.width, 6); // 0..5 inclusive
  assert.equal(world.meta.worldArea.height, 6);
});

test('a real build plus a handful of far-flung stray points keeps the build and drops the strays', () => {
  // Mirrors 1315736126: one dense cluster, several isolated single points
  // scattered far away in different directions.
  const primary: { x: number; y: number }[] = [];
  for (let x = 0; x < 20; x++) {
    for (let y = 0; y < 20; y++) primary.push({ x: 4000 + x, y: 4000 + y });
  }
  const strays = [
    { x: 0, y: 0 },
    { x: 0, y: 3000 },
    { x: 5900, y: 0 },
    { x: 2000, y: 0 },
  ];
  const world = loadWorldFromArrayBuffer(buildEdenBuffer([...primary, ...strays]));

  assert.equal(world.meta.chunks.length, primary.length);
  assert.equal(world.meta.worldArea.width, 20);
  assert.equal(world.meta.worldArea.height, 20);
  // None of the stray coordinates should survive into the kept chunk list.
  for (const s of strays) {
    assert.ok(!world.meta.chunks.some((c) => c.x === s.x && c.y === s.y));
  }
});

test('two real builds close enough together both survive', () => {
  const a = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 0, y: 1 },
  ];
  const b = [
    { x: 40, y: 0 },
    { x: 41, y: 0 },
  ];
  // 20,000 filler chunks scattered thinly across a huge span so the naive
  // bounding box is forced over MAX_CHUNK_AREA and clustering actually runs,
  // without needing anywhere near MAX_CHUNK_COUNT chunks.
  const filler: { x: number; y: number }[] = [];
  for (let i = 0; i < 20_000; i++) filler.push({ x: i * 200, y: i % 7 });

  const world = loadWorldFromArrayBuffer(buildEdenBuffer([...a, ...b, ...filler]));
  const kept = new Set(world.meta.chunks.map((c) => `${c.x},${c.y}`));
  for (const c of [...a, ...b]) assert.ok(kept.has(`${c.x},${c.y}`), `expected (${c.x},${c.y}) to survive`);
});

test('one single sparse cluster that is implausibly large throws WorldParseError', () => {
  // A diagonal chain of points each within CLUSTER_RADIUS (64) of the next
  // in both axes, so they all connect into one giant cluster whose own 2D
  // bounding box already exceeds the area cap — there's no smaller "primary
  // cluster" to fall back to.
  const chain: { x: number; y: number }[] = [];
  for (let i = 0; i < 500; i++) chain.push({ x: i * 32, y: i * 32 });

  assert.throws(() => loadWorldFromArrayBuffer(buildEdenBuffer(chain)), WorldParseError);
});

test('an empty chunk table throws a clear error instead of producing a 0x0 PNG', () => {
  // Found live: world 1623093424's stored .eden.zip decompresses to a
  // 263-byte XML error page (a failed download), not real eden data — its
  // chunk table is empty. This used to silently succeed with a broken
  // ~65-byte 0x0 PNG instead of failing.
  assert.throws(() => loadWorldFromArrayBuffer(buildEdenBuffer([])), WorldParseError);
});
