#!/usr/bin/env ts-node
"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const fs_1 = __importDefault(require("fs"));
const path_1 = __importDefault(require("path"));
const World_1 = require("./World");
const worldMeta_1 = require("./worldMeta");
// Meta-only counterpart to generate-map.ts: parses just far enough to read
// the technical fields (format, chunk dimensions, sky color, seed, spawn) and
// skips renderNormalMap entirely — the expensive per-pixel pass generate-map.ts
// needs but backfilling metadata onto worlds that already have a map.png does
// not.
if (process.argv.length < 4) {
    console.error("Usage: ts-node generate-meta.ts <eden_file> <output.json>");
    process.exit(1);
}
const edenFilePath = path_1.default.resolve(process.argv[2]);
const outputPath = path_1.default.resolve(process.argv[3]);
try {
    if (!fs_1.default.existsSync(edenFilePath)) {
        console.error(`File not found: ${edenFilePath}`);
        process.exit(1);
    }
    const buffer = fs_1.default.readFileSync(edenFilePath);
    // Node.js pools small Buffers in a shared ArrayBuffer; slice to get the exact bytes.
    const ab = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
    const world = (0, World_1.loadWorldFromArrayBuffer)(ab);
    fs_1.default.mkdirSync(path_1.default.dirname(outputPath), { recursive: true });
    fs_1.default.writeFileSync(outputPath, JSON.stringify((0, worldMeta_1.metaFromWorld)(world)));
    console.log(`✔ meta → ${outputPath}`);
}
catch (err) {
    console.error(`⚠ ${err.message}`);
    process.exit(1);
}
