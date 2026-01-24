import { Painted, Unpainted } from '../domain/MapColors';
import type { WorldData } from '../domain/World';

type Pixel = { r: number; g: number; b: number; a: number };

const setPixel = (data: Uint8ClampedArray, width: number, x: number, y: number, color: Pixel) => {
  const idx = (y * width + x) * 4;
  data[idx] = color.r;
  data[idx + 1] = color.g;
  data[idx + 2] = color.b;
  data[idx + 3] = color.a;
};

const paintedPixel = (index: number): Pixel => {
  const c = Painted[index] ?? { r: 0, g: 0, b: 0 };
  return { ...c, a: 255 };
};

const unpaintedPixel = (index: number): Pixel => {
  const c = Unpainted[index] ?? { r: 0, g: 0, b: 0 };
  return { ...c, a: 255 };
};

/**
 * Render a top-down normal map (first visible block per column) akin to Mapping.NormalMap.
 * Uses the world’s chunk layout to compute canvas coordinates.
 */
export function renderNormalMap(world: WorldData): ImageData {
  const { meta, bytes } = world;
  const width = meta.worldArea.width * 16;
  const height = meta.worldArea.height * 16;
  const data = new Uint8ClampedArray(width * height * 4);

  for (const chunk of meta.chunks) {
    const baseX = (chunk.x - meta.worldArea.x) * 16;
    const baseY = (chunk.y - meta.worldArea.y) * 16;
    const address = chunk.address;

    // Calculate how many vertical chunks are available in this column
    // Each chunk is 12288 bytes (8192 blocks + 4096 colors)
    const chunkDataSize = 12288;
    const maxAvailableChunks = Math.min(
      16, // Support up to 256 blocks (16 chunks)
      Math.floor((bytes.length - address) / chunkDataSize)
    );

    for (let x = 0; x < 16; x++) {
      for (let y = 0; y < 16; y++) {
        let painted = false;
        // iterate from top (baseHeight=maxAvailableChunks-1, z=15) downwards
        // Support up to 16 chunks (256 blocks) instead of just 4 chunks (64 blocks)
        for (let baseHeight = maxAvailableChunks - 1; baseHeight >= 0 && !painted; baseHeight--) {
          for (let z = 15; z >= 0; z--) {
            const blockIdx = address + baseHeight * 8192 + x * 256 + y * 16 + z;
            const colorIdx = address + baseHeight * 8192 + x * 256 + y * 16 + z + 4096;
            
            if (blockIdx >= bytes.length || colorIdx >= bytes.length) continue;
            
            const block = bytes[blockIdx];
            if (block === 0) continue;

            const paint = bytes[colorIdx];
            if (paint !== 0) {
              setPixel(data, width, baseX + x, baseY + y, paintedPixel(paint - 1));
            } else {
              setPixel(data, width, baseX + x, baseY + y, unpaintedPixel(block - 1));
            }
            painted = true;
            break;
          }
        }
      }
    }
  }

  return new ImageData(data, width, height);
}

