"""Curated vocabulary. Plain editable dicts — the archivist grows these while
working; no code change is needed elsewhere in the pipeline.

KEYWORDS is lifted from shortlist_worlds.py:18-63 (the category taxonomy the
user flagged as the genuinely valuable part of that prior script).
MULTILINGUAL merges the German/French/Spanish structure & gameplay sets from
eden_triage_v2_1.py:17-65 — the corpus is genuinely international (FLUGHAFEN
cmg, Le Bluflaym Royaume, ciudad satelite, Francis Letzebuerg, Ritterburg).
CONCEPT_MAP powers concept search: a query like "theme park" expands to the
terms actual builders used instead of that literal phrase.
CHAT_* encodes the Handle'CHANNEL'message spam-chat convention documented in
the project plan — 'red' is the largest channel (131,688 rows, 2015-02-18 to
2026-04-26) but not the only one.
"""

KEYWORDS = {
    "iteration": [
        "alpha", "beta", "prototype", "test", "rev", "revision", "build",
        "update", "pass", "phase", "draft", "concept", "wip", "iteration",
        "progress", "workshop", "demo", "proof", "milestone", "checkpoint",
        "refactor", "overhaul", "rebuild", "tuning", "rebalance",
    ],
    "architecture": [
        "station", "base", "outpost", "hub", "terminal", "dock", "port",
        "facility", "plant", "complex", "control", "sector", "zone", "module",
        "reactor", "hangar", "runway", "bridge", "tunnel", "metro", "rail",
        "harbor", "dockyard", "shipyard", "platform", "tower", "gate",
        "subway", "railway", "freight", "depot", "warehouse", "barracks",
        "checkpoint", "launch", "silo", "pipeline", "dam",
    ],
    "worldbuilding": [
        "city", "district", "capital", "ruins", "colony", "settlement",
        "stronghold", "citadel", "fort", "realm", "domain", "archive",
        "kingdom", "empire", "republic", "province", "region", "island",
        "archipelago", "continent", "metropolis", "village", "town",
        "borough", "neighborhood", "shrine", "sanctuary", "monastery",
        "frontier", "wasteland", "bay",
    ],
    "realworld": [
        "museum", "library", "airport", "hospital", "school", "factory",
        "laboratory", "lab", "research", "observatory", "bunker", "vault",
        "cathedral", "castle", "fortress", "palace", "temple", "stadium",
        "mall", "plaza", "arena", "harbor", "port", "aquarium", "zoo",
        "university", "college", "campus", "prison", "courthouse",
    ],
    "gameplay": [
        "adventure", "quest", "puzzle", "maze", "parkour", "challenge",
        "arena", "ctf", "rpg", "survival", "campaign", "mission",
        "dungeon", "course", "trial", "gauntlet", "speedrun",
        "battle", "boss", "raid", "questline", "minigame", "race", "ride",
    ],
    "older": [
        "classic", "old", "legacy", "original", "remake", "redux",
        "definitive", "final", "vintage", "retro",
    ],
    "other": [
        "unfinished", "abandoned", "experiment", "testbed", "sandbox",
        "replica", "project", "buildlog", "worklog", "diary", "dev",
    ],
}

STRONG_KEYWORDS = set(
    KEYWORDS["realworld"]
    + KEYWORDS["gameplay"]
    + ["facility", "complex", "station", "base", "citadel", "stronghold", "replica"]
)

MULTILINGUAL = {
    "structure": {
        "de": ["stadt", "basis", "anlage", "komplex", "zone", "sektor",
               "bezirk", "hafen", "bunker", "labor", "fabrik", "turm"],
        "fr": ["ville", "base", "complexe", "zone", "secteur", "district",
               "port", "bunker", "laboratoire", "usine", "tour"],
        "es": ["ciudad", "base", "complejo", "zona", "sector", "distrito",
               "puerto", "bunker", "laboratorio", "fabrica", "torre"],
    },
    "gameplay": {
        "de": ["abenteuer", "quest", "ratsel", "parkour", "geschichte",
               "mission", "kampagne", "labyrinth", "fahrt", "rennen"],
        "fr": ["aventure", "quete", "puzzle", "parkour", "histoire",
               "mission", "campagne", "labyrinthe", "course", "defi"],
        "es": ["aventura", "mision", "puzzle", "parkour", "historia",
               "campana", "laberinto", "carrera", "reto"],
    },
}

# Concept search: query -> expansion terms, run through the lexical backend.
CONCEPT_MAP = {
    "theme park": [
        "coaster", "rides", "ride", "fairground", "carnival", "ferris",
        "log flume", "amusement", "rollercoaster", "waterpark", "funfair",
        "carousel",
    ],
    "airport": [
        "airport", "runway", "terminal", "hangar", "airfield", "airstrip",
        "flughafen", "aeropuerto", "aeroport",
    ],
    "hotel": ["hotel", "resort", "motel", "inn", "lodge", "suites"],
    "city": [
        "city", "metropolis", "downtown", "district", "town", "capital",
        "stadt", "ville", "ciudad",
    ],
    "castle": [
        "castle", "fortress", "citadel", "keep", "stronghold", "burg",
        "chateau", "castillo",
    ],
    "space": [
        "space", "station", "orbit", "rocket", "launch", "spaceship",
        "spacecraft", "colony", "moon", "mars",
    ],
    "medieval": [
        "medieval", "midevil", "kingdom", "castle", "knight", "village",
        "town", "realm",
    ],
    "war": ["war", "battle", "military", "army", "combat", "siege", "fort"],
    "parkour": ["parkour", "obby", "course", "gauntlet", "trial"],
    "maze": ["maze", "labyrinth", "puzzle"],
}

# Handle'CHANNEL'message — the largest coherent subculture in the archive.
# Row counts are the corpus-wide totals measured at build time (see CLAUDE.md).
CHAT_CHANNEL_TAGS = {
    "red", "lava", "war", "ktpn", "abce", "dotd", "rb", "mam", "pscp",
}

# Punctuation-escape tokens: since the game keyboard only accepts
# [A-Za-z0-9 '], players wrapped punctuation-as-word in apostrophes.
CHAT_ESCAPE_TOKENS = {
    "qm": "?", "xd": "XD", "excl": "!", "period": ".", "comma": ",",
    "colon": ":", "semi": ";", "dash": "-", "hyphen": "-", "amp": "&",
    "at": "@", "hash": "#", "lol": "lol", "smh": "smh",
}

# Loose bag of words that mark a name as conversational sentence fragments
# rather than a world title — drawn straight from the reconstructed chat log
# in the project plan (Scc/Jon/Allie, 2015-02-28).
CHAT_WORDS = {
    "im", "ur", "u", "dont", "cant", "wont", "cuz", "gonna", "wanna",
    "haha", "omg", "wtf", "brb", "idk", "tho", "yall", "gotta", "kinda",
    "sry", "pls", "plz", "thx", "ok", "okay", "yeah", "yea", "nope", "yep",
    "huh", "guess", "glad", "alone", "leave", "quit", "back", "something",
    "would", "really", "actually", "just", "its", "thats", "whats", "hows",
    "wish", "bad", "good", "join", "here", "bruh", "lmao", "lmfao", "smh",
    "asf", "fr", "ngl", "bet", "cap", "sus",
}

DEFAULT_NAME_LANGUAGE_HINTS = {"en", "de", "fr", "es"}
