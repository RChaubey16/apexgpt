"""Alias normalisation, identical to the ingestion loader's (a test checks it).

The alias tables store `normalise_alias(name)`, and their check constraint
enforces the format: lowercase ASCII letters and digits, single spaces. Lookups
must normalise the question the same way or "Pérez" would never match "perez".
Copied from ingestion/structured/aliases.py because the backend can't import
the ingestion package (separate uv projects).
"""

import re
import unicodedata

# Letters NFKD does not decompose into ASCII + combining marks.
_TRANSLITERATE = str.maketrans(
    {"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss",
     "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ð": "d", "þ": "th", "ı": "i"}
)  # fmt: skip
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise_alias(text: str) -> str:
    """'Sergio Pérez' -> 'sergio perez'; "O'Ward" -> 'o ward'; 'Räikkönen' -> 'raikkonen'."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", ascii_only.lower()).strip()
