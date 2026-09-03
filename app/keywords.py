from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from app.paths import stopwords_path

STOPWORDS_PATH = stopwords_path()

NIKUD_RE = re.compile(r"[\u0591-\u05C7]")
TOKEN_RE = re.compile(r"[\u0590-\u05FF]{2,}|[A-Za-z]{2,}")
DATE_DMY_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")
DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
MAX_KEYWORDS = 20


def _load_stopwords() -> set[str]:
    if not STOPWORDS_PATH.exists():
        return set()
    words: set[str] = set()
    for line in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.add(normalize_token(word))
    return words


def strip_nikud(text: str) -> str:
    return NIKUD_RE.sub("", text)


def normalize_token(token: str) -> str:
    token = strip_nikud(token)
    token = unicodedata.normalize("NFC", token)
    return token.casefold()


_STOPWORDS: set[str] | None = None


def stopwords() -> set[str]:
    global _STOPWORDS
    if _STOPWORDS is None:
        _STOPWORDS = _load_stopwords()
    return _STOPWORDS


def tokenize(text: str) -> list[str]:
    skipped = stopwords()
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(strip_nikud(text)):
        token = normalize_token(match.group(0))
        if len(token) < 2 or token in skipped:
            continue
        tokens.append(token)
    return tokens


def detect_language(text: str) -> str:
    hebrew = sum(1 for ch in text if "\u0590" <= ch <= "\u05ff")
    latin = sum(1 for ch in text if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    if hebrew and latin:
        return "he+en"
    if hebrew:
        return "he"
    if latin:
        return "en"
    return "unknown"


def extract_dates(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(year: int, month: int, day: int) -> None:
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
            return
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        if iso not in seen:
            seen.add(iso)
            found.append(iso)

    for day, month, year in DATE_DMY_RE.findall(text):
        year_i = int(year)
        if year_i < 100:
            year_i += 2000 if year_i < 80 else 1900
        add(year_i, int(month), int(day))

    for year, month, day in DATE_ISO_RE.findall(text):
        add(int(year), int(month), int(day))

    return found


from app.taxonomy import load_taxonomy


def _trigger_list(keywords: str, name: str) -> list[str]:
    parts = [part.strip() for part in keywords.replace(";", ",").split(",")]
    parts.append(name)
    return [part for part in parts if part]


def _score_triggers(text: str, keywords: list[str], triggers: list[str]) -> int:
    tokens = set(tokenize(text)) | {normalize_token(word) for word in keywords}
    haystack = strip_nikud(text).casefold()
    hits = 0
    for trigger in triggers:
        normalized = normalize_token(trigger)
        if not normalized:
            continue
        if normalized.isascii():
            if normalized in tokens:
                hits += 1
        elif normalized in tokens or normalized in haystack:
            hits += 1
    return hits


def suggest_category(text: str, keywords: list[str]) -> tuple[str, str]:
    best = "אחר"
    best_sub = ""
    best_hits = 0
    for category in load_taxonomy():
        parent_hits = _score_triggers(text, keywords, _trigger_list(category.get("keywords") or "", category["name"]))
        sub_name = ""
        sub_hits = 0
        for sub in category.get("subcategories") or []:
            score = _score_triggers(text, keywords, _trigger_list(sub.get("keywords") or "", sub["name"]))
            if score > sub_hits:
                sub_hits = score
                sub_name = sub["name"]
        total = parent_hits + sub_hits
        if total > best_hits:
            best_hits = total
            best = category["name"]
            best_sub = sub_name if sub_hits else ""
    return best, best_sub


def extract_keywords(
    text: str,
    doc_frequencies: dict[str, int] | None = None,
    corpus_size: int = 0,
    limit: int = MAX_KEYWORDS,
) -> list[tuple[str, float]]:
    tokens = tokenize(text)
    if not tokens:
        return []
    tf = Counter(tokens)
    total = len(tokens)
    scored: list[tuple[str, float]] = []
    df = doc_frequencies or {}
    n_docs = max(corpus_size, 1)
    for word, count in tf.items():
        term_freq = count / total
        idf = math.log((n_docs + 1) / (df.get(word, 0) + 1)) + 1.0
        length_boost = 1.0 + min(len(word), 8) / 16.0
        scored.append((word, round(term_freq * idf * length_boost, 6)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]


def analyze_text(
    text: str,
    doc_frequencies: dict[str, int] | None = None,
    corpus_size: int = 0,
) -> dict:
    keywords = extract_keywords(text, doc_frequencies, corpus_size)
    keyword_words = [word for word, _ in keywords]
    category, subcategory = suggest_category(text, keyword_words)
    return {
        "keywords": keywords,
        "category": category,
        "subcategory": subcategory,
        "dates": extract_dates(text),
        "language": detect_language(text),
    }
