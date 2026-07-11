#!/usr/bin/env ts-node
import fs from "fs";
import path from "path";
import { PNG } from "pngjs";
import { loadWorldFromArrayBuffer } from "./World";
import { renderNormalMap } from "./renderNormalMap";

if (process.argv.length < 4) {
  console.error("Usage: ts-node generate-map.ts <eden_file> <output.png>");
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
  const { data, width, height } = renderNormalMap(world);

  const png = new PNG({ width, height });
  png.data = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const pngBuffer = PNG.sync.write(png);

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, pngBuffer);
  console.log(`✔ ${width}×${height} → ${outputPath}`);
} catch (err) {
  console.error(`⚠ ${(err as Error).message}`);
  process.exit(1);
}
