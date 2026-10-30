import unicodedata


def word_counts(text):
    if not isinstance(text, str):
        raise TypeError('text must be str')
    counts, current = {}, []
    def finish():
        if current:
            word = unicodedata.normalize('NFC', ''.join(current))
            word = unicodedata.normalize('NFC', word.casefold())
            counts[word] = counts.get(word, 0) + 1
            current.clear()
    for char in text:
        category = unicodedata.category(char)[0]
        if category in {'L', 'N'} or (category == 'M' and current):
            current.append(char)
        elif category != 'M':
            finish()
    finish()
    return list(counts.items())
