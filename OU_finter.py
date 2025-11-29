#https://www.smogon.com/dex/sv/formats/ou/
import json
import re
import requests

# 1) Smogon OU VR page (static HTML with all OU mons)
OU_VR_URL = "https://www.smogon.com/forums/threads/sv-ou-indigo-disk-viability-ranking-thread-update-on-post-1101.3734134/"

# 2) Load page text
print("[INFO] Downloading OU VR page...")
resp = requests.get(OU_VR_URL, timeout=30)
resp.raise_for_status()
page_text = resp.text.lower()

# 3) Load your full dictionary
with open("pokemon_en_zh.json", "r", encoding="utf-8") as f:
    data = json.load(f)

all_pokemon = data.get("pokemon", [])

def name_in_page(en_name: str, text: str) -> bool:
    """
    Return True if en_name appears as a word in text.
    e.g. 'Tyranitar' matches '... Tyranitar ...', but not 'Tyranitarsomething'
    """
    pattern = r"\b" + re.escape(en_name.lower()) + r"\b"
    return re.search(pattern, text) is not None

filtered_pokemon = []
for p in all_pokemon:
    en_name = p.get("en", "")
    if not en_name:
        continue
    if name_in_page(en_name, page_text):
        filtered_pokemon.append(p)

print(f"[INFO] {len(filtered_pokemon)} Pokémon kept out of {len(all_pokemon)}")

# 4) Save new JSON with only OU mons
filtered_data = {
    "pokemon": filtered_pokemon,
    # keep moves if you want, or empty them:
    "moves": data.get("moves", [])
}

with open("pokemon_ou_en_zh.json", "w", encoding="utf-8") as f:
    json.dump(filtered_data, f, ensure_ascii=False, indent=2)

print("[INFO] Saved filtered dictionary to pokemon_ou_en_zh.json")
