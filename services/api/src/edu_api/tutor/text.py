"""Text normalisation shared by retrieval and safeguarding.

French and Haitian Creole only. Everything here is deterministic and has no
model behind it: accents are folded, question words and articles are dropped,
and a crude six-letter prefix stands in for a stemmer. The prefix is the one
trick that matters: it maps ``soustraire`` / ``soustrait`` (French) and
``soustrè`` (Creole) to the same token.
"""

from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "ʼ": "'"})  # noqa: RUF001
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")


#: Function words that say nothing about the topic. Listed after accent folding.
def words(listing: str) -> frozenset[str]:
    """A set of words from a space-separated listing (keeps long word lists readable)."""
    return frozenset(listing.split())


STOPWORDS = words(
    # French
    "le la les un une des de du d l et ou a au aux en dans sur pour par avec sans ce cet cette "
    "ces que qui quoi qu est sont on nous vous il elle ils elles je tu me te se ne pas plus si "
    "comment pourquoi quand quel quelle quels quelles y c s n j m t mon ma mes ton ta tes son sa "
    "ses fait faire faut peut peux veux veut dois doit etre avoir ai as cela ca ceci donc alors "
    "mais car tres bien aussi comme leur leurs moi toi lui "
    # Haitian Creole
    "yon lan nan an yo ki sa se pou ak e epi oswa mwen ou w li nou ka te ap gen sou poukisa "
    "kijan kisa kote kile ke tankou fe dwe vle di mande tanpri ban eske konsa tou menm "
    "pa m "
)

#: Single letters are noise, except the usual names of an unknown in mathematics.
_KEPT_SINGLE_LETTERS = frozenset({"x", "y", "z"})
_STEM_LENGTH = 6


def normalize(text: str) -> str:
    """Lower-case, fold accents and typographic apostrophes, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES).lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", folded).strip()


def stem(token: str) -> str:
    if token.isdigit():
        return token
    if len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token[:_STEM_LENGTH]


def tokenize(text: str) -> list[str]:
    """Topic-bearing tokens of ``text``, in order, stemmed."""
    tokens: list[str] = []
    for word in _WORD.findall(normalize(text)):
        if word in STOPWORDS:
            continue
        if len(word) == 1 and not word.isdigit() and word not in _KEPT_SINGLE_LETTERS:
            continue
        tokens.append(stem(word))
    return tokens


def estimate_tokens(text: str) -> int:
    """A deliberately HIGH estimate of model tokens, used only to reserve budget.

    One token per three UTF-8 bytes over-counts French and Creole prose for
    every common tokenizer. Settlement uses the provider's reported usage.
    """
    return (len(text.encode("utf-8")) + 2) // 3
