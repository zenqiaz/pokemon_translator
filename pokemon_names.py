import requests

POKEAPI_BASE = "https://pokeapi.co/api/v2"

def get_all_pokemon_slugs():
    url = f"{POKEAPI_BASE}/pokemon-species?limit=20000&offset=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # Each result: {"name": "metagross", "url": ".../pokemon-species/376/"}
    slugs = [entry["name"] for entry in data["results"]]
    return slugs

slugs = get_all_pokemon_slugs()
print(len(slugs), slugs[:10])