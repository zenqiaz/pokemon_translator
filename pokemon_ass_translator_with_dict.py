#pokemon_ass_translator_with_dict.py
#!/usr/bin/env python
'''
ollama pull qwen2:7b
ollama serve
python pokemon_ass_translator_with_dict.py test_fixed_70_75.ass test_cn.ass   --model qwen2:7b   --source-lang en   --target-lang zh   --dict pokemon_en_zh_full.json
'''

import argparse
import json
import re
import sys
import time
import textwrap
from typing import Dict, List

import requests
import pysubs2

COMMON_MOVE_BLOCKLIST = {
    "Absorb",
    "Counter",
    "Recover",
    "Protect",
    "Curse",
    "Return",
    "Rest",
    "Endure",
    "Pound",
    "Cut",
    "Strength",
    "Withdraw",
    "Lick",
    "Swift",
    # add more here if you see bad behaviour
}
# ---------- 1. Pokémon dictionary wrapper ----------

class PokemonDictionary:
    def __init__(self, json_path: str):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.entries = data
        self.en_terms: List[str] = []
        self.en_to_entry: Dict[str, Dict] = {}

        # Pokémon species: always include
        for item in data.get("pokemon", []):
            en_name = item.get("en")
            if not en_name:
                continue
            self.en_terms.append(en_name)
            self.en_to_entry[en_name] = item

        # Moves: skip ones in the blocklist
        for item in data.get("moves", []):
            en_name = item.get("en")
            if not en_name:
                continue
            if en_name in COMMON_MOVE_BLOCKLIST:
                continue  # ❌ don’t use this move in glossary
            self.en_terms.append(en_name)
            self.en_to_entry[en_name] = item

        # Precompute lowercase names for quick search
        self.en_terms_lower = [name.lower() for name in self.en_terms]

        self._compiled = [
            (name, re.compile(r"\b" + re.escape(name) + r"\b", flags=re.IGNORECASE))
            for name in self.en_terms
        ]

        print(f"[INFO] Loaded {len(self.en_terms)} Pokémon terms from {json_path}", file=sys.stderr)

    def glossary_for_line(self, text: str, target_lang: str = "zh") -> Dict[str, str]:
        """
        Find all Pokémon terms present in `text` and return a mapping:
        English name -> localized name in `target_lang` (fallback to EN if missing).
        """
        glossary: Dict[str, str] = {}
        lang_key = target_lang.lower()

        for en_name, pattern in self._compiled:
            if pattern.search(text):
                entry = self.en_to_entry[en_name]
                # Try exact target_lang key first (e.g. "zh"), fallback to "zh-Hans"/"zh_cn" etc if you add them.
                # For now assume your JSON uses "zh".
                localized = entry.get(lang_key) or entry.get("zh") or en_name
                glossary[en_name] = localized

        return glossary


# ---------- 2. Ollama translator with per-line glossary ----------

class OllamaPokemonTranslator:
    def __init__(
        self,
        model: str,
        source_lang: str,
        target_lang: str,
        pokedict: PokemonDictionary,
        api_url: str = "http://localhost:11434/api/generate",
        sleep_on_error: float = 3.0,
    ):
        """
        Translation backend using Ollama /api/generate and a Pokémon-aware glossary.

        - model: Ollama model name, e.g. 'qwen2:7b'
        - source_lang: 'en'
        - target_lang: 'zh', 'ja', etc.
        - pokedict: PokemonDictionary instance for glossary
        - api_url: Ollama /api/generate endpoint
        """
        self.model = model
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.pokedict = pokedict
        self.api_url = api_url.rstrip("/")
        self.sleep_on_error = sleep_on_error

        self.system_prompt = textwrap.dedent(f"""
        You are an expert translator for video game content, especially competitive Pokémon videos.

        Requirements:
        - Source language: {self.source_lang}
        - Target language: {self.target_lang}
        - Input is one subtitle line, not long paragraphs.
        - Preserve meaning and tone; make it sound like natural spoken commentary.
        - DO NOT add explanations, notes, or extra sentences.
        - Output ONLY the translated line, no quotes, no metadata.

        Pokémon terminology:
        - Use the official target-language names for Pokémon and moves whenever given.
        - If the glossary below provides mappings, you MUST use those exact target names.
        - If a term is not in the glossary and you are unsure, keep the original name as-is.
        """)

    def _build_glossary_section(self, text: str) -> str:
        glossary = self.pokedict.glossary_for_line(text, target_lang=self.target_lang)
        if not glossary:
            return ""

        lines = [f"- {src} -> {tgt}" for src, tgt in glossary.items()]
        return (
            "\n\nKnown Pokémon term mappings for this line:\n"
            + "\n".join(lines)
            + "\n\nWhen translating, you MUST use these exact target names for these terms.\n"
        )

    def _call_ollama(self, text: str) -> str:
        glossary_section = self._build_glossary_section(text)

        full_prompt = (
            self.system_prompt.strip()
            + glossary_section
            + "\n\n"
            + f"Translate this subtitle line from {self.source_lang} to {self.target_lang}:\n{text}"
        )

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
        }

        while True:
            try:
                resp = requests.post(self.api_url, json=payload, timeout=120)
                if resp.status_code != 200:
                    print(f"[ERROR] Ollama HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
                    resp.raise_for_status()

                data = resp.json()
                translated = (data.get("response") or "").strip()
                if not translated:
                    print("[WARN] Empty translation from model.", file=sys.stderr)
                return translated

            except Exception as e:
                print(f"[WARN] Ollama request failed: {e}", file=sys.stderr)
                print(f"Retrying after {self.sleep_on_error} seconds...", file=sys.stderr)
                time.sleep(self.sleep_on_error)

    def translate(self, text: str) -> str:
        return self._call_ollama(text)


# ---------- 3. Subtitle pipeline (ASS/SRT) ----------

class SubtitleTranslator:
    def __init__(self, src_path: str, translator: OllamaPokemonTranslator):
        self.src_path = src_path
        self.translator = translator

    def translate_by_line(self):
        subs = pysubs2.load(self.src_path)
        total_lines = len(subs)

        for idx, line in enumerate(subs, start=1):
            original_text = line.text
            if not original_text.strip():
                continue

            print(f"[{idx}/{total_lines}] {original_text}", file=sys.stderr)
            translated = self.translator.translate(original_text)
            print(f"        -> {translated}", file=sys.stderr)

            # Bilingual line: original on top, translation on second line
            line.text = original_text + r"\N" + translated

        return subs


# ---------- 4. CLI entry point ----------

def main():
    parser = argparse.ArgumentParser(
        description="Pokémon-aware subtitle translator for .ass/.srt using Ollama and a dictionary."
    )
    parser.add_argument("input", help="Input .ass or .srt subtitle file (normalized)")
    parser.add_argument(
        "output",
        nargs="?",
        help="Output subtitle file (default: <input_basename>_pokemon.ass)",
    )
    parser.add_argument(
        "--model",
        default="qwen2:7b",
        help="Ollama model name (default: qwen2:7b)",
    )
    parser.add_argument(
        "--source-lang",
        default="en",
        help="Source language code (default: en)",
    )
    parser.add_argument(
        "--target-lang",
        default="zh",
        help="Target language code (default: zh)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434/api/generate",
        help="Ollama /api/generate URL (default: http://localhost:11434/api/generate)",
    )
    parser.add_argument(
        "--dict",
        required=True,
        help="Path to Pokémon en-zh dictionary JSON (e.g. pokemon_ou_en_zh.json)",
    )

    args = parser.parse_args()

    # Determine output path
    if args.output is None:
        if args.input.lower().endswith(".ass"):
            out = args.input[:-4] + "_translated.ass"
        elif args.input.lower().endswith(".srt"):
            out = args.input[:-4] + "_translated.srt"
        else:
            out = args.input + "_translated.ass"
    else:
        out = args.output

    pokedict = PokemonDictionary(args.dict)

    translator_backend = OllamaPokemonTranslator(
        model=args.model,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        pokedict=pokedict,
        api_url=args.ollama_url,
    )

    pipeline = SubtitleTranslator(args.input, translator_backend)
    subs = pipeline.translate_by_line()
    subs.save(out, encoding="utf-8")

    print(f"Done. Saved bilingual subtitles to: {out}")


if __name__ == "__main__":
    main()
