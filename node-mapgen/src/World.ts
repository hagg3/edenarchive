import { ungzip } from 'pako';

export type ChunkPointer = {
  address: number;
  x: number;
  y: number;
};

export type WorldArea = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type WorldMeta = {
  name: string;
  skyColor: number;
  worldArea: WorldArea;
  chunks: ChunkPointer[];
  numBands: number; // 4 for 64z legacy worlds, 16 for 256z New Dawn worlds
};

export type WorldData = {
  meta: WorldMeta;
  bytes: Uint8Array;
};

export function loadWorldFromArrayBuffer(buffer: ArrayBuffer): WorldData {
  const raw = new Uint8Array(buffer);
  const bytes = isGzip(raw) ? decompressGzip(raw) : raw;

  // Sky color: pick the most frequent non-14 value across positions 132–148.
  const skyCandidates: number[] = [];
  for (let i = 132; i <= 148; i++) {
    if (bytes[i] !== 14) skyCandidates.push(bytes[i]);
  }
  const skyColor = skyCandidates.length === 0 ? 14 : mode(skyCandidates);

  // Chunk pointer table offset at bytes 32–35 (little-endian u32).
  const chunkPointerStart =
    bytes[35] * 0x1000000 +
    bytes[34] * 0x10000 +
    bytes[33] * 0x100 +
    bytes[32];

  // Name: null-terminated ASCII at bytes 40–75.
  let nameEnd = 40;
  while (nameEnd <= 75 && bytes[nameEnd] !== 0) nameEnd++;
  const name = new TextDecoder('ascii').decode(bytes.slice(40, nameEnd));

  // Each chunk pointer is 16 bytes: X@[0..2] i16, Y@[4..6] i16, offset@[8..12] u32.
  const chunks: ChunkPointer[] = [];
  let idx = chunkPointerStart;
  while (idx + 16 <= bytes.length) {
    // Signed 16-bit little-endian for chunk coordinates (can be negative).
    const xRaw = bytes[idx] | (bytes[idx + 1] << 8);
    const yRaw = bytes[idx + 4] | (bytes[idx + 5] << 8);
    const x = xRaw >= 0x8000 ? xRaw - 0x10000 : xRaw;
    const y = yRaw >= 0x8000 ? yRaw - 0x10000 : yRaw;
    const address =
      bytes[idx + 8] |
      (bytes[idx + 9] << 8) |
      (bytes[idx + 10] << 16) |
      (bytes[idx + 11] * 0x1000000);
    if (address > 0 && address < bytes.length) {
      chunks.push({ x, y, address });
    }
    idx += 16;
  }

  const worldArea = computeArea(chunks);

  // Detect 64z (4 bands) vs 256z (16 bands) by minimum gap between chunk file offsets.
  // Matches the algorithm in eden-world-editor's parse_world_inner (lib.rs).
  const addresses = chunks.map((c) => c.address).sort((a, b) => a - b);
  let minGap = 32768;
  for (let i = 1; i < addresses.length; i++) {
    minGap = Math.min(minGap, addresses[i] - addresses[i - 1]);
  }
  const numBands = minGap >= 131072 ? 16 : 4;

  return { meta: { name, skyColor, worldArea, chunks, numBands }, bytes };
}

function isGzip(data: Uint8Array): boolean {
  return data.length >= 2 && data[0] === 0x1f && data[1] === 0x8b;
}

function decompressGzip(data: Uint8Array): Uint8Array {
  return ungzip(data);
}

function mode(values: number[]): number {
  const freq = new Map<number, number>();
  for (const v of values) {
    freq.set(v, (freq.get(v) ?? 0) + 1);
  }
  let best = 14;
  let bestCount = -1;
  for (const [v, c] of freq.entries()) {
    if (c > bestCount) {
      best = v;
      bestCount = c;
    }
  }
  return best;
}

function computeArea(chunks: ChunkPointer[]): WorldArea {
  const xs = chunks.map((c) => c.x);
  const ys = chunks.map((c) => c.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  return {
    x: minX,
    y: minY,
    width: maxX - minX + 1,
    height: maxY - minY + 1,
  };
}
