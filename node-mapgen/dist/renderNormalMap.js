"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.renderNormalMap = renderNormalMap;
const MapColors_1 = require("./MapColors");
function renderNormalMap(world) {
    const { meta, bytes } = world;
    const width = meta.worldArea.width * 16;
    const height = meta.worldArea.height * 16;
    const data = new Uint8ClampedArray(width * height * 4);
    for (const chunk of meta.chunks) {
        const baseX = (chunk.x - meta.worldArea.x) * 16;
        const baseY = (chunk.y - meta.worldArea.y) * 16;
        const addr = chunk.address;
        for (let lx = 0; lx < 16; lx++) {
            for (let ly = 0; ly < 16; ly++) {
                // Scan from the top band downward. Each band covers 16 z-levels (8192 bytes).
                // Use meta.numBands (4 for 64z worlds, 16 for 256z) to avoid reading into adjacent chunks.
                let found = false;
                for (let band = meta.numBands - 1; band >= 0 && !found; band--) {
                    for (let lz = 15; lz >= 0; lz--) {
                        const bi = addr + band * 8192 + lx * 256 + ly * 16 + lz;
                        const pi = bi + 4096;
                        if (bi >= bytes.length || pi >= bytes.length)
                            continue;
                        const block = bytes[bi];
                        if (block === 0)
                            continue;
                        const paint = bytes[pi];
                        const off = ((baseY + ly) * width + (baseX + lx)) * 4;
                        const c = paint !== 0
                            ? (MapColors_1.Painted[paint - 1] ?? { r: 0, g: 0, b: 0 })
                            : (MapColors_1.Unpainted[block - 1] ?? { r: 0, g: 0, b: 0 });
                        data[off] = c.r;
                        data[off + 1] = c.g;
                        data[off + 2] = c.b;
                        data[off + 3] = 255;
                        found = true;
                        break;
                    }
                }
            }
        }
    }
    return { data, width, height };
}
