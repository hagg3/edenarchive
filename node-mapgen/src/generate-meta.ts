#!/usr/bin/env ts-node
import fs from "fs";
import path from "path";
import { loadWorldFromArrayBuffer } from "./World";
import { metaFromWorld } from "./worldMeta";

// Meta-only counterpart to generate-map.ts: parses just far enough to read
// the technical fields (format, chunk dimensions, sky color, seed, spawn) and
// skips renderNormalMap entirely — the expensive per-pixel pass generate-map.ts
// needs but backfilling metadata onto worlds that already have a map.png does
// not.

if (process.argv.length < 4) {
  console.error("Usage: ts-node generate-meta.ts <eden_file> <output.json>");
  process.exit(1);
}

const edenFilePath = path.resolve(process.argv[2]);
const outputPath = path.resolve(process.argv[3]);

try {
  if (!fs.existsSync(edenFilePath)) {
    console.error(`File not found: ${edenFilePath}`);
    process.exit(1);
  }

  const buffer = fs.readFileSync(edenFilePath);
  // Node.js pools small Buffers in a shared ArrayBuffer; slice to get the exact bytes.
  const ab = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  const world = loadWorldFromArrayBuffer(ab as ArrayBuffer);

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(metaFromWorld(world)));
  console.log(`✔ meta → ${outputPath}`);
} catch (err) {
  console.error(`⚠ ${(err as Error).message}`);
  process.exit(1);
}
