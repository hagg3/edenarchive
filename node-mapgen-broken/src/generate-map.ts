#!/usr/bin/env ts-node

import fs from "fs";
import path from "path";
import { loadWorldFromArrayBuffer } from "./world";
import { renderNormalMap } from "./rendernormalmap";

// CLI arguments: <eden_file> <output_png>
if (process.argv.length < 4) {
  console.error("Usage: ts-node generate-map.ts <eden_file> <output_png>");
  process.exit(1);
}

const edenFilePath = path.resolve(process.argv[2]);
const outputPath = path.resolve(process.argv[3]);

try {
  if (!fs.existsSync(edenFilePath)) {
    console.error(`❌ Eden file not found: ${edenFilePath}`);
    process.exit(1);
  }

  const buffer = fs.readFileSync(edenFilePath);
  const worldData = loadWorldFromArrayBuffer(buffer);

  // Generate map
  const pngBuffer = renderNormalMap(worldData);

  // Ensure output folder exists
  const outDir = path.dirname(outputPath);
  fs.mkdirSync(outDir, { recursive: true });

  fs.writeFileSync(outputPath, pngBuffer);
  console.log(`✔ Map generated at ${outputPath}`);
} catch (err) {
  console.error(`⚠ Failed to generate map: ${(err as Error).message}`);
  process.exit(1); // optional: Python script ignores failure
}
