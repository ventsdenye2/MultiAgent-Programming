import unicodedata


def _normalize_word(word):
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", word).casefold())


def word_counts(text: str) -> list[tuple[str, int]]:
    if not isinstance(text, str):
        raise TypeError("text must be a str")

    counts = {}
    current = []

    def flush():
        if current:
            word = _normalize_word("".join(current))
            current.clear()
            if word:
                counts[word] = counts.get(word, 0) + 1

    for char in text:
        kind = unicodedata.category(char)[0]
        if kind == "L" or kind == "N":
            current.append(char)
        elif kind == "M":
            if current:
                current.append(char)
        else:
            flush()
    flush()

    return list(counts.items())
