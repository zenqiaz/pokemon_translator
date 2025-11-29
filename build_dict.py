import json
import re
import time
import sys
from typing import Dict, Any, List, Optional

import requests

BASE_URL = "https://pokeapi.co/api/v2"
LANG_EN = "en"
# PokeAPI uses zh-Hans / zh-Hant; here we choose Simplified Chinese.
LANG_ZH_POKEAPI = "zh-Hans"

# politeness delay between per-item requests (seconds)
DELAY = 0.1


def get_json(url: str) -> Dict[str, Any]:
    """GET a URL and return JSON, with simple retry."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[WARN] Request failed ({url}): {e}", file=sys.stderr)
            if attempt == 2:
                raise
            time.sleep(2.0)


def extract_id_from_url(url: str) -> int:
    """PokeAPI URLs end with /<id>/; extract that id."""
    m = re.search(r"/(\d+)/?$", url)
    return int(m.group(1)) if m else -1


def fetch_all_slugs(endpoint: str) -> List[Dict[str, Any]]:
    """
    Fetch all resources for an endpoint that supports `?limit=&offset=`,
    e.g. pokemon-species, move.

    Returns list of dicts: {"name": slug, "url": url}
    """
    url = f"{BASE_URL}/{endpoint}?limit=20000&offset=0"
    data = get_json(url)
    results = data.get("results", [])
    print(f"[INFO] {endpoint}: got {len(results)} entries", file=sys.stderr)
    return results


def pick_name(names_list: List[Dict[str, Any]], lang: str) -> Optional[str]:
    """
    Given PokeAPI's 'names' array, pick the name for a given language code.
    """
    for entry in names_list:
        lang_name = entry.get("language", {}).get("name")
        if lang_name == lang:
            return entry.get("name")
    return None


def build_pokemon_list_en_zh() -> List[Dict[str, Any]]:
    """
    Build list of Pokémon species with id, slug, EN, and ZH names.
    Uses /pokemon-species and /pokemon-species/{slug}.
    """
    species_list = fetch_all_slugs("pokemon-species")
    out: List[Dict[str, Any]] = []

    for i, entry in enumerate(species_list, start=1):
        slug = entry["name"]
        url = entry["url"]
        pid = extract_id_from_url(url)

        detail_url = f"{BASE_URL}/pokemon-species/{slug}"
        detail = get_json(detail_url)
        names = detail.get("names", [])

        name_en = pick_name(names, LANG_EN) or slug.capitalize()
        name_zh = pick_name(names, LANG_ZH_POKEAPI)

        out.append(
            {
                "id": pid,
                "slug": slug,
                "en": name_en,
                "zh": name_zh,
            }
        )

        if i % 50 == 0:
            print(f"[INFO] Pokémon {i}/{len(species_list)}: {slug}", file=sys.stderr)
        time.sleep(DELAY)

    return out


def build_move_list_en_zh() -> List[Dict[str, Any]]:
    """
    Build list of moves with id, slug, EN, and ZH names.
    Uses /move and /move/{slug}.
    """
    move_list = fetch_all_slugs("move")
    out: List[Dict[str, Any]] = []

    for i, entry in enumerate(move_list, start=1):
        slug = entry["name"]
        url = entry["url"]
        mid = extract_id_from_url(url)

        detail_url = f"{BASE_URL}/move/{slug}"
        detail = get_json(detail_url)
        names = detail.get("names", [])

        name_en = pick_name(names, LANG_EN) or slug.replace("-", " ").title()
        name_zh = pick_name(names, LANG_ZH_POKEAPI)

        out.append(
            {
                "id": mid,
                "slug": slug,
                "en": name_en,
                "zh": name_zh,
            }
        )

        if i % 50 == 0:
            print(f"[INFO] Moves {i}/{len(move_list)}: {slug}", file=sys.stderr)
        time.sleep(DELAY)

    return out


# ---- run the builder ----

print("[INFO] Building Pokémon and move EN-ZH dictionary from PokeAPI...", file=sys.stderr)
pokemon = build_pokemon_list_en_zh()
moves = build_move_list_en_zh()

data = {"pokemon": pokemon, "moves": moves}

output_path = "pokemon_en_zh.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"[INFO] Saved {len(pokemon)} Pokémon and {len(moves)} moves to {output_path}", file=sys.stderr)
