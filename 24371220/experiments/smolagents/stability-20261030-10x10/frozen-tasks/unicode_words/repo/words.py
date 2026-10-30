import re


def word_counts(text):
    counts = {}
    for word in re.findall(r'[a-z]+', text.lower()):
        counts[word] = counts.get(word, 0) + 1
    return list(counts.items())
