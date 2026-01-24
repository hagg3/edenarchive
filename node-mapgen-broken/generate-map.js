#!/usr/bin/env node
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const fs_1 = require("fs");
const canvas_1 = require("canvas");
const world_1 = require("./world");
const renderNormalMap_1 = require("./renderNormalMap");
function main() {
    const [, , edenPath, outputPath] = process.argv;
    if (!edenPath || !outputPath) {
        console.error("Usage: generate-map <input.eden> <output.png>");
        process.exit(1);
    }
    try {
        const buffer = (0, fs_1.readFileSync)(edenPath);
        const world = (0, world_1.loadWorldFromArrayBuffer)(buffer.buffer);
        const imageData = (0, renderNormalMap_1.renderNormalMap)(world);
        const canvas = (0, canvas_1.createCanvas)(imageData.width, imageData.height);
        const ctx = canvas.getContext("2d");
        ctx.putImageData(imageData, 0, 0);
        (0, fs_1.writeFileSync)(outputPath, canvas.toBuffer("image/png"));
        process.exit(0);
    }
    catch (err) {
        console.error("Map generation failed:", err);
        process.exit(2);
    }
}
main();
