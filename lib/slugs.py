"""Random two-word slug generator for expert-mode projects."""

import random

ADJECTIVES = [
    "bold", "brave", "calm", "cool", "dark", "deep", "fair", "fast",
    "fine", "fond", "free", "glad", "gold", "good", "gray", "keen",
    "kind", "lean", "long", "loud", "mild", "neat", "nice", "pale",
    "pure", "rare", "rich", "safe", "slim", "soft", "sure", "tall",
    "tidy", "vast", "warm", "wide", "wild", "wise", "quick", "quiet",
    "sharp", "sweet", "clear", "fresh", "grand", "light", "prime",
    "royal", "vivid", "young",
]

NOUNS = [
    "atlas", "badge", "bloom", "cedar", "cloud", "coral", "crane", "delta",
    "dune", "ember", "fern", "flame", "forge", "frost", "grove", "haven",
    "heron", "ivory", "jewel", "lake", "lark", "maple", "marsh", "mist",
    "moon", "oasis", "olive", "pearl", "pine", "plume", "prism", "quail",
    "ridge", "river", "sage", "shell", "shore", "spark", "stone", "storm",
    "swift", "thorn", "tide", "vale", "wave", "wren", "crest", "falcon",
    "orbit", "lotus",
]


def generate_slug(existing_slugs: set[str] | None = None) -> str:
    """Generate a unique adjective-noun slug (e.g. 'bold-crane').

    With 50x50 = 2500 combinations, collisions are rare for <100 projects.
    """
    for _ in range(200):
        slug = f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"
        if existing_slugs is None or slug not in existing_slugs:
            return slug
    raise RuntimeError("Could not generate unique slug after 200 attempts")
