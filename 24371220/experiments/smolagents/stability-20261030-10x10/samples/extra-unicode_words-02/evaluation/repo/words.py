import unicodedata


def word_counts(text: str) -> list[tuple[str, int]]:
    if not isinstance(text, str):
        raise TypeError("text must be a str")

    counts: dict[str, int] = {}
    current: list[str] = []

    def finish_word() -> None:
        if not current:
            return
        word = unicodedata.normalize("NFC", "".join(current))
        word = word.casefold()
        word = unicodedata.normalize("NFC", word)
        counts[word] = counts.get(word, 0) + 1
        current.clear()

    for char in text:
        category = unicodedata.category(char)
        kind = category[0]

        if kind in ("L", "N"):
            current.append(char)
        elif kind == "M":
            if current:
                current.append(char)
        else:
            finish_word()

    finish_word()
    return list(counts.items())
