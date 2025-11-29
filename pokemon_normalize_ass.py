#pokemon_normalize_ass.py
#把一部分首字母大写的单词替换成相近的宝可梦名字
#usage:
#python pokemon_normalize_ass.py test.ass.ass test_fixed_70_75.ass --dict pokemon_ou_en_zh.json
#!/usr/bin/env python
#!/usr/bin/env python
import argparse
import json
import re
import sys
from typing import List, Dict, Tuple

import pysubs2
from rapidfuzz import fuzz, process

#这里是白名单单词
DO_NOT_FIX_UNIGRAMS = {
    "Dance",
    "Punch",
    "Slide",
    "Rock",
    "Beam",
    "Wave",
    "Blast",
    "Kick",
    "Ball",
    "Throw",
    "Storm",
    "Wind",
    "Spin",
    "Hit",
    "Thunder",
    "Trick",
    "Room",
    "Dragon",
    "Draco",
    "Grass",
    "Fire",
}
# ---------- 1. Load meta Pokémon list (OU / UU / Ubers only) ----------
class MetaPokemon:
    """
    meta_json_path: small OU/UU/Ubers list used for fuzzy corrections
    whitelist_json_path: big full Pokédex list used to protect true names
    """

    def __init__(self, meta_json_path: str, whitelist_json_path: str | None = None):
        # --- meta list (small) ---
        with open(meta_json_path, "r", encoding="utf-8") as f:
            meta_data = json.load(f)

        self.meta_names: List[str] = []
        self.meta_map: Dict[str, Dict] = {}

        for item in meta_data.get("pokemon", []):
            en_name = item.get("en")
            if not en_name:
                continue
            self.meta_names.append(en_name)
            self.meta_map[en_name.lower()] = item

        print(f"[INFO] Loaded {len(self.meta_names)} meta Pokémon names", file=sys.stderr)

        # --- whitelist (big) ---
        if whitelist_json_path is None:
            # fallback: just protect meta names themselves
            self.whitelist_names_lower = set(self.meta_map.keys())
        else:
            with open(whitelist_json_path, "r", encoding="utf-8") as f:
                full_data = json.load(f)

            whitelist = set()
            for item in full_data.get("pokemon", []):
                en_name = item.get("en")
                if not en_name:
                    continue
                whitelist.add(en_name.lower())

            self.whitelist_names_lower = whitelist
            print(f"[INFO] Loaded {len(self.whitelist_names_lower)} whitelist Pokémon names", file=sys.stderr)

    # ---- 1-gram matching ----

    def best_unigram_match(self, token: str, threshold: int = 80) -> Tuple[str | None, int]:
        """
        Fuzzy match a single token (e.g. 'Terranitar') to meta Pokémon names.

        Returns (canonical_en, score) or (None, score).
        """
        if not self.meta_names:
            return None, 0

        result = process.extractOne(token, self.meta_names, scorer=fuzz.ratio)
        if result is None:
            return None, 0

        best, score, _ = result
        if score < threshold:
            return None, score
        return best, score

    # ---- 2-gram matching ----

    def best_bigram_match(self, join_token: str, threshold: int = 80) -> Tuple[str | None, int]:
        """
        Fuzzy match a joined bigram (e.g. 'SweetCoon') to meta names
        for cases like 'Sweet Coon' -> 'Suicune'.
        """
        if not self.meta_names:
            return None, 0

        result = process.extractOne(join_token, self.meta_names, scorer=fuzz.ratio)
        if result is None:
            return None, 0

        best, score, _ = result
        if score < threshold:
            return None, score
        return best, score



# ---------- 2. 1-gram + 2-gram line normalization ----------

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


def _is_title_like(word: str) -> bool:
    """
    True for tokens that look like Pokémon names:
    - First letter uppercase
    - Not ALL CAPS (to avoid acronyms)
    """
    return word and word[0].isupper() and not word.isupper()


def fix_line_with_meta(line: str, meta: MetaPokemon) -> str:
    """
    Normalize Pokémon names in a single line using:

    1) 2-grams of Title-case words (e.g. 'Sweet Coon' -> 'Suicune')
    2) 1-grams of Title-case words (e.g. 'Terranitar' -> 'Tyranitar')

    Heuristics:
    - Only consider Title-case tokens (Metagross, Tyranitar, Suicune).
    - For bigrams: both tokens Title-case; join them without space; fuzzy-match.
    - For unigrams: same first letter, small length difference.
    """
    # Collect tokens and their character spans
    tokens = list(WORD_RE.finditer(line))
    if not tokens:
        return line

    words = [m.group(0) for m in tokens]
    n = len(words)

    # Replacements as (token_start_index, token_end_index, replacement_text)
    replacements: List[Tuple[int, int, str]] = []

    # ---------- 2-gram stage: fix split names like "Sweet Coon" -> "Suicune" ----------
    used = set()
    for i in range(n - 1):
        if i in used:
            continue

        w1, w2 = words[i], words[i + 1]

        # Only Title-case tokens
        if not (_is_title_like(w1) and _is_title_like(w2)):
            continue

        base1 = w1.rstrip(".,'").replace("’", "")
        base2 = w2.rstrip(".,'").replace("’", "")

        # 1) NEW: if either word is already a known Pokémon (full whitelist), skip
        if base1.lower() in meta.whitelist_names_lower:
            continue
        if base2.lower() in meta.whitelist_names_lower:
            continue

        # 2) NEW: don't cross sentence boundaries (avoid "Weavile. But")
        between = line[tokens[i].end():tokens[i + 1].start()]
        if any(ch in between for ch in ".?!;\n"):
            continue

        join_candidate = base1 + base2  # "SweetCoon"

        best, score = meta.best_bigram_match(join_candidate, threshold=90)
        if not best:
            continue

        # Extra guard: same first letter & similar length
        if best[0].lower() != join_candidate[0].lower():
            continue
        if abs(len(best) - len(join_candidate)) > 3:
            continue

        # Accept: replace tokens i..i+2 with single name `best`
        replacements.append((i, i + 2, best))
        used.update({i, i + 1})

    # ---------- 1-gram stage: fix single tokens like "Terranitar" -> "Tyranitar" ----------

    # Mark which word indices are already replaced by a bigram
    occupied = set()
    for s, e, _ in replacements:
        occupied.update(range(s, e))

    for i, w in enumerate(words):
        if i in occupied:
            continue
        if len(w) < 4:
            continue
        if not _is_title_like(w):
            continue

        base = w.rstrip(".,'").replace("’", "")

        # --- NEW: if this is already a known Pokémon name (any tier), don't touch it ---
        if base.lower() in meta.whitelist_names_lower:
            continue

        # Hyphens: unchanged from before ...
        if "-" in base:
            parts = base.split("-")
            if any(part in DO_NOT_FIX_UNIGRAMS for part in parts):
                continue
            if base.lower() not in meta.meta_map:
                continue
            continue  # exact known hyphen Pokémon -> leave as-is

        if base in DO_NOT_FIX_UNIGRAMS:
            continue

        # Already exactly a meta Pokémon name? leave it
        if base.lower() in meta.meta_map:
            continue

        best, score = meta.best_unigram_match(base, threshold=75)
        if not best or best == base:
            continue
        if best[0].lower() != base[0].lower():
            continue
        if abs(len(best) - len(base)) > 2:
            continue

        replacements.append((i, i + 1, best))

    # No changes
    if not replacements:
        return line

    # ---------- Apply replacements on the original string (right-to-left) ----------

    # Turn token indices into character spans
    char_repls: List[Tuple[int, int, str]] = []
    for s_idx, e_idx, new_text in replacements:
        start_char = tokens[s_idx].start()
        end_char = tokens[e_idx - 1].end()
        char_repls.append((start_char, end_char, new_text))

    # Sort by start descending to avoid messing indexes when replacing
    char_repls.sort(key=lambda x: x[0], reverse=True)

    fixed = line
    for start_char, end_char, new_text in char_repls:
        fixed = fixed[:start_char] + new_text + fixed[end_char:]

    return fixed


# ---------- 3. Run over a whole .ass/.srt file ----------

def normalize_file(input_path: str, output_path: str, meta_json_path: str, whitelist_json_path: str):
    meta = MetaPokemon(meta_json_path,whitelist_json_path)
    subs = pysubs2.load(input_path)
    total = len(subs)

    for idx, line in enumerate(subs, start=1):
        text = line.text
        if not text.strip():
            continue

        fixed = fix_line_with_meta(text, meta)
        if fixed != text:
            print(f"[{idx}/{total}] FIX:", file=sys.stderr)
            print(f"  {text}", file=sys.stderr)
            print(f"  -> {fixed}", file=sys.stderr)

        line.text = fixed

    subs.save(output_path, encoding="utf-8")
    print(f"[INFO] Saved normalized subtitles to: {output_path}", file=sys.stderr)


# ---------- 4. CLI ----------

def main():
    parser = argparse.ArgumentParser(
        description="Normalize Pokémon names in subtitles using 1-gram and 2-gram fuzzy matching."
    )
    parser.add_argument("input", help="Input .ass or .srt subtitle file")
    parser.add_argument("output", help="Output .ass or .srt subtitle file (normalized)")
    parser.add_argument(
        "--dict",
        required=True,
        help="Path to meta Pokémon JSON (e.g. pokemon_ou_en_zh.json)")
    parser.add_argument(
        "--full",
        required=True,
        help="Path to all Pokémon list JSON (e.g. pokemon_ou_en_zh.json)")
    
    

    args = parser.parse_args()
    normalize_file(args.input, args.output, args.dict, args.full)


if __name__ == "__main__":
    main()
