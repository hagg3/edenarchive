#!/usr/bin/env ts-node
"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const fs_1 = __importDefault(require("fs"));
const path_1 = __importDefault(require("path"));
const pngjs_1 = require("pngjs");
const World_1 = require("./World");
const renderNormalMap_1 = require("./renderNormalMap");
const worldMeta_1 = require("./worldMeta");
if (process.argv.length < 4) {
    console.error("Usage: ts-node generate-map.ts <eden_file> <output.png>");
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
    const { data, width, height } = (0, renderNormalMap_1.renderNormalMap)(world);
    const png = new pngjs_1.PNG({ width, height });
    png.data = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
    const pngBuffer = pngjs_1.PNG.sync.write(png);
    fs_1.default.mkdirSync(path_1.default.dirname(outputPath), { recursive: true });
    fs_1.default.writeFileSync(outputPath, pngBuffer);
    // meta.json sidecar: technical fields already computed as a side effect of
    // rendering, written alongside the map so the archive site/admin app can
    // surface them without re-parsing the .eden file.
    const metaPath = path_1.default.join(path_1.default.dirname(outputPath), 'meta.json');
    fs_1.default.writeFileSync(metaPath, JSON.stringify((0, worldMeta_1.metaFromWorld)(world)));
    console.log(`✔ ${width}×${height} → ${outputPath}`);
}
catch (err) {
    console.error(`⚠ ${err.message}`);
    process.exit(1);
}
