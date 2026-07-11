"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.metaFromWorld = metaFromWorld;
function metaFromWorld(world) {
    const { meta } = world;
    return {
        format: meta.numBands === 16 ? '256z' : '64z',
        chunkWidth: meta.worldArea.width,
        chunkHeight: meta.worldArea.height,
        skyColor: meta.skyColor,
        seed: meta.seed,
        spawnX: meta.spawnX,
        spawnY: meta.spawnY,
    };
}
