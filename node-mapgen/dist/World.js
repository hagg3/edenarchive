"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.WorldParseError = void 0;
exports.loadWorldFromArrayBuffer = loadWorldFromArrayBuffer;
const pako_1 = require("pako");
// The chunk pointer table has no length field or end marker (confirmed
// against MROB.txt's reverse-engineering notes) — it's read by scanning
// 16-byte records from the header's directory offset to end of file, keeping
// any record whose address field looks plausible. For most worlds that's
// exactly right. Two failure modes found live against the real archive:
//
// - World 1770253120 is a genuine ~6.3 GB world (compresses to a deceptively
//   small ~18 MB gzip stream — Eden's terrain is extremely repetitive).
//   Scanning that much data throws off tens of millions of coincidentally
//   "plausible" 16-byte records well past the real table, and
//   `Math.min(...xs)` on an array that size threw "Maximum call stack size
//   exceeded" (spreading millions of args blows V8's call stack). No
//   legitimate Eden world's chunk table has anywhere near this many real
//   entries — MAX_CHUNK_COUNT below turns that into a clean, fast error
//   instead of a crash after the fact.
// - World 1315736126 is a genuine but tiny (~20 MB, 626-chunk) world whose
//   chunks form several spatially separate builds — a dense ~572-chunk
//   cluster around x≈4050–4150, a small ~38-chunk cluster near the origin,
//   and a sprinkling of much smaller/isolated ones out to x≈5911 (all of
//   these entries are *within* the real chunk-table region — this isn't
//   over-scanning past the table like the case above, the world genuinely
//   has scattered builds). `computeArea`'s naive min/max bounding box
//   stretched to cover all of them (5912×5912 chunks), and `renderNormalMap`
//   tried to allocate a canvas for it — ~35 GB, which is what actually hung
//   the process (slow allocation/paging, not an infinite loop). Median-
//   distance trimming doesn't work here (the 572-chunk cluster dominates the
//   median, so nothing gets dropped) — MAX_CHUNK_AREA below instead triggers
//   cluster-based trimming (see computeArea): group chunks by proximity, then
//   greedily keep the largest clusters that still fit the size budget.
const MAX_CHUNK_COUNT = 2000000;
// ~5.7x the largest known real rendered map in the archive (5632×12304 =
// ~69.3M px) as of 2026-07-11 — generous headroom for legitimately huge
// worlds, while still catching multi-billion-pixel garbage bounding boxes.
const MAX_CANVAS_PIXELS = 400000000;
const MAX_CHUNK_AREA = MAX_CANVAS_PIXELS / 256; // 256 px per chunk (16×16)
// Chebyshev distance (in chunks) within which two chunks are considered part
// of the same build/cluster. Generous enough to keep one sprawling build
// together, small enough to separate genuinely distant, unrelated ones.
const CLUSTER_RADIUS = 64;
// Above this many chunks, clustering (which is roughly O(n) but still does
// real work per chunk) isn't worth attempting — MAX_CHUNK_COUNT already
// keeps this far below what's reachable in practice.
const MAX_CHUNKS_FOR_CLUSTERING = 200000;
class WorldParseError extends Error {
}
exports.WorldParseError = WorldParseError;
function loadWorldFromArrayBuffer(buffer) {
    const raw = new Uint8Array(buffer);
    const bytes = isGzip(raw) ? decompressGzip(raw) : raw;
    // Sky color: pick the most frequent non-14 value across positions 132–148.
    const skyCandidates = [];
    for (let i = 132; i <= 148; i++) {
        if (bytes[i] !== 14)
            skyCandidates.push(bytes[i]);
    }
    const skyColor = skyCandidates.length === 0 ? 14 : mode(skyCandidates);
    // Chunk pointer table offset at bytes 32–35 (little-endian u32).
    const chunkPointerStart = bytes[35] * 0x1000000 +
        bytes[34] * 0x10000 +
        bytes[33] * 0x100 +
        bytes[32];
    // Name: null-terminated ASCII at bytes 40–75.
    let nameEnd = 40;
    while (nameEnd <= 75 && bytes[nameEnd] !== 0)
        nameEnd++;
    const name = new TextDecoder('ascii').decode(bytes.slice(40, nameEnd));
    // Each chunk pointer is 16 bytes: X@[0..2] i16, Y@[4..6] i16, offset@[8..12] u32.
    const chunks = [];
    let idx = chunkPointerStart;
    while (idx + 16 <= bytes.length) {
        // Signed 16-bit little-endian for chunk coordinates (can be negative).
        const xRaw = bytes[idx] | (bytes[idx + 1] << 8);
        const yRaw = bytes[idx + 4] | (bytes[idx + 5] << 8);
        const x = xRaw >= 0x8000 ? xRaw - 0x10000 : xRaw;
        const y = yRaw >= 0x8000 ? yRaw - 0x10000 : yRaw;
        const address = bytes[idx + 8] |
            (bytes[idx + 9] << 8) |
            (bytes[idx + 10] << 16) |
            (bytes[idx + 11] * 0x1000000);
        if (address > 0 && address < bytes.length) {
            chunks.push({ x, y, address });
            if (chunks.length > MAX_CHUNK_COUNT) {
                throw new WorldParseError(`chunk pointer table scan found over ${MAX_CHUNK_COUNT.toLocaleString()} ` +
                    'entries — this world is either too large for node-mapgen or its ' +
                    'chunk table is corrupt');
            }
        }
        idx += 16;
    }
    if (chunks.length === 0) {
        // Matches eden-world-editor's parse_world_inner: "No valid chunks
        // found". Found live: world 1623093424's stored .eden.zip decompresses
        // to a 263-byte XML error page (a failed download saved in place of the
        // real world), not eden data at all — its "chunk table" is empty, and
        // rendering it used to silently succeed with a 0×0 canvas (a broken
        // ~65-byte PNG) instead of failing. That's a corrupt-source-data problem,
        // not a compression one, but it's the same "fail loudly, not silently"
        // principle as the checks above.
        throw new WorldParseError('no valid chunks found — this file is either not a real Eden world or its data is corrupt');
    }
    const { area: worldArea, chunks: keptChunks, droppedOutliers } = computeArea(chunks);
    if (droppedOutliers > 0) {
        console.error(`⚠ dropped ${droppedOutliers} outlier chunk record(s) far from the main ` +
            'cluster (likely misread bytes past the real chunk table, not real chunks)');
    }
    if (worldArea.width * worldArea.height > MAX_CHUNK_AREA) {
        throw new WorldParseError(`world area ${worldArea.width}×${worldArea.height} chunks is implausibly large ` +
            'even after outlier trimming — refusing to allocate a canvas for it');
    }
    // Detect 64z (4 bands) vs 256z (16 bands) by minimum gap between chunk file offsets.
    // Matches the algorithm in eden-world-editor's parse_world_inner (lib.rs).
    const addresses = keptChunks.map((c) => c.address).sort((a, b) => a - b);
    let minGap = 32768;
    for (let i = 1; i < addresses.length; i++) {
        minGap = Math.min(minGap, addresses[i] - addresses[i - 1]);
    }
    const numBands = minGap >= 131072 ? 16 : 4;
    return { meta: { name, skyColor, worldArea, chunks: keptChunks, numBands }, bytes };
}
function isGzip(data) {
    return data.length >= 2 && data[0] === 0x1f && data[1] === 0x8b;
}
function decompressGzip(data) {
    return (0, pako_1.ungzip)(data);
}
function mode(values) {
    const freq = new Map();
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
function boundingBox(chunks) {
    // Manual min/max, not Math.min(...xs) — spreading millions of array
    // elements as call arguments overflows V8's call stack (see the
    // MAX_CHUNK_COUNT comment above; this guards the same failure mode
    // defensively even below that ceiling).
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const c of chunks) {
        if (c.x < minX)
            minX = c.x;
        if (c.x > maxX)
            maxX = c.x;
        if (c.y < minY)
            minY = c.y;
        if (c.y > maxY)
            maxY = c.y;
    }
    return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
}
function unionBBox(a, b) {
    const minX = Math.min(a.x, b.x);
    const minY = Math.min(a.y, b.y);
    const maxX = Math.max(a.x + a.width - 1, b.x + b.width - 1);
    const maxY = Math.max(a.y + a.height - 1, b.y + b.height - 1);
    return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
}
/** Groups chunk indices by proximity (Chebyshev distance <= radius transitively)
 * using a grid-bucketed union-find — average O(n) rather than the O(n²) a
 * naive all-pairs distance check would need. */
function clusterByProximity(chunks, radius) {
    const cellOf = (v) => Math.floor(v / radius);
    const buckets = new Map();
    chunks.forEach((c, i) => {
        const k = `${cellOf(c.x)},${cellOf(c.y)}`;
        const arr = buckets.get(k);
        if (arr)
            arr.push(i);
        else
            buckets.set(k, [i]);
    });
    const parent = chunks.map((_, i) => i);
    const find = (a) => {
        while (parent[a] !== a) {
            parent[a] = parent[parent[a]];
            a = parent[a];
        }
        return a;
    };
    const union = (a, b) => {
        const ra = find(a);
        const rb = find(b);
        if (ra !== rb)
            parent[ra] = rb;
    };
    chunks.forEach((c, i) => {
        const ccx = cellOf(c.x);
        const ccy = cellOf(c.y);
        for (let dx = -1; dx <= 1; dx++) {
            for (let dy = -1; dy <= 1; dy++) {
                const neighbors = buckets.get(`${ccx + dx},${ccy + dy}`);
                if (!neighbors)
                    continue;
                for (const j of neighbors) {
                    if (j <= i)
                        continue;
                    const other = chunks[j];
                    if (Math.abs(other.x - c.x) <= radius && Math.abs(other.y - c.y) <= radius) {
                        union(i, j);
                    }
                }
            }
        }
    });
    const groups = new Map();
    chunks.forEach((_, i) => {
        const r = find(i);
        const arr = groups.get(r);
        if (arr)
            arr.push(i);
        else
            groups.set(r, [i]);
    });
    return [...groups.values()];
}
function computeArea(chunks) {
    if (chunks.length === 0) {
        return { area: { x: 0, y: 0, width: 0, height: 0 }, chunks, droppedOutliers: 0 };
    }
    const naive = boundingBox(chunks);
    if (naive.width * naive.height <= MAX_CHUNK_AREA) {
        return { area: naive, chunks, droppedOutliers: 0 };
    }
    if (chunks.length > MAX_CHUNKS_FOR_CLUSTERING) {
        // Too many chunks to cluster cheaply; report the naive (oversized) area
        // and let the caller's own MAX_CHUNK_AREA check fail cleanly.
        return { area: naive, chunks, droppedOutliers: 0 };
    }
    // The naive bounding box is implausibly large for the chunk count. Group
    // chunks into spatially separate builds, keep the single largest cluster
    // (by chunk count) as the primary render, then only fold in additional
    // clusters if doing so doesn't blow the area far past what the primary
    // cluster alone needed.
    //
    // A pure "keep unioning while under the global budget" greedy (tried
    // first) doesn't work: against 1315736126 it let a single 1-chunk outlier
    // at (3843, 0) merge in late, because unioning it with the primary
    // cluster's bbox happened to stay *narrow* in X even though it stretched
    // *height* out to cover the primary cluster's y-range down to 0 — the
    // union's total area (266×4110 chunks) slipped just under the global cap
    // despite representing one meaningless pixel floating in a mostly-empty
    // 6.7-million-pixel canvas. The fix is a *local* budget scaled to the
    // primary cluster's own size, not just the global cap: a merge is only
    // worth it if the combined area stays within a small multiple of what the
    // primary cluster needed by itself.
    const clusterIndices = clusterByProximity(chunks, CLUSTER_RADIUS);
    const clusters = clusterIndices
        .map((idxs) => {
        const members = idxs.map((i) => chunks[i]);
        return { members, bbox: boundingBox(members) };
    })
        .sort((a, b) => b.members.length - a.members.length);
    const primary = clusters[0];
    const primaryArea = primary.bbox.width * primary.bbox.height;
    const localBudget = Math.min(MAX_CHUNK_AREA, Math.max(primaryArea * 4, 1024));
    let area = primary.bbox;
    const kept = [...primary.members];
    let droppedOutliers = chunks.length - primary.members.length;
    for (const cluster of clusters.slice(1)) {
        const candidate = unionBBox(area, cluster.bbox);
        if (candidate.width * candidate.height <= localBudget) {
            area = candidate;
            kept.push(...cluster.members);
            droppedOutliers -= cluster.members.length;
        }
    }
    return { area, chunks: kept, droppedOutliers };
}
