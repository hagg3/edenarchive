import { ungzip } from 'pako';
import { Painting } from './Paintings';

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
};

export type WorldData = {
  meta: WorldMeta;
  bytes: Uint8Array;
};

export function loadWorldFromArrayBuffer(buffer: ArrayBuffer): WorldData {
  const raw = new Uint8Array(buffer);
  const bytes = isGzip(raw) ? decompressGzip(raw) : raw;

  // Sky color: pick the most frequent non-14 value across positions 132-148 (inclusive).
  const skyCandidates: number[] = [];
  for (let i = 132; i <= 148; i++) {
    if (bytes[i] !== 14) skyCandidates.push(bytes[i]);
  }
  const skyColor =
    skyCandidates.length === 0
      ? 14
      : mode(skyCandidates);

  // Chunk pointer start index is a 32-bit little-endian int at bytes[32..35]
  const chunkPointerStart =
    bytes[35] * 256 * 256 * 256 +
    bytes[34] * 256 * 256 +
    bytes[33] * 256 +
    bytes[32];

  // Name: ASCII slice from 40 until null or 75.
  let nameEnd = 40;
  while (nameEnd <= 75 && bytes[nameEnd] !== 0) nameEnd++;
  const name = new TextDecoder('ascii').decode(bytes.slice(40, nameEnd));

  const chunks: ChunkPointer[] = [];
  let idx = chunkPointerStart;
  while (idx + 11 < bytes.length) {
    const x = bytes[idx + 1] * 256 + bytes[idx];
    const y = bytes[idx + 5] * 256 + bytes[idx + 4];
    const address =
      bytes[idx + 11] * 256 * 256 * 256 +
      bytes[idx + 10] * 256 * 256 +
      bytes[idx + 9] * 256 +
      bytes[idx + 8];
    chunks.push({ x, y, address });
    idx += 16;
  }

  const worldArea = computeArea(chunks);

  const meta: WorldMeta = { name, skyColor, worldArea, chunks };
  return { meta, bytes };
}

function isGzip(data: Uint8Array): boolean {
  return data.length >= 2 && data[0] === 0x1f && data[1] === 0x8b;
}

const decompressGzip = (data: Uint8Array): Uint8Array => ungzip(data);

function mode(values: number[]): number {
  const freq = new Map<number, number>();
  for (const v of values) {
    freq.set(v, (freq.get(v) ?? 0) + 1);
  }
  let best = Painting.Unpainted;
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
    height: maxY - minY + 1
  };
}

