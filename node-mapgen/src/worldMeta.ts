import type { WorldData } from './World';

/** JSON-serializable technical metadata written as `meta.json` alongside a
 * world's map.png, and read back by admin/core/mapgen.py to fold into the
 * world's front matter (worldformat/chunkwidth/chunkheight/skycolor/seed/
 * spawnx/spawny). Field names here are camelCase; the Python side translates
 * them to the corpus's lowercase front-matter keys. */
export type WorldMetaJson = {
  format: '64z' | '256z';
  chunkWidth: number;
  chunkHeight: number;
  skyColor: number;
  seed: number;
  spawnX: number | null;
  spawnY: number | null;
};

export function metaFromWorld(world: WorldData): WorldMetaJson {
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
