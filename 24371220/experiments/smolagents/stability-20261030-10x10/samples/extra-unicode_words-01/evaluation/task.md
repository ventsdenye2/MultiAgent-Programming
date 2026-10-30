# Unicode word frequencies

Only modify `words.py`. Implement `word_counts(text: str) -> list[tuple[str,int]]`.
Use Unicode character categories (unicodedata.category): a word starts with a
letter (category L*) or number (N*) and continues across letters, numbers and
combining marks (M*). A mark without an active word is ignored. Any other
character ends the current word: underscore, hyphen, apostrophe, whitespace,
symbols and emoji are separators. Do not normalize the input before finding
word boundaries. Thus 'a\u0301' is one word but a leading combining mark is ignored.

Normalize each completed word with NFC, then casefold, then NFC again. Count
equal normalized words together. Return (word,count) tuples in first normalized
occurrence order. Do not use locale rules, NFKC or ASCII-only regexes. Empty or
separator-only input returns []. Input is a str; other input types raise TypeError.
Keep every letter of scripts without spaces in the same word (no segmentation).

Create a plan, fully read words.py, run `python -m pytest -q` before first write;
after final write run the full same command, finish the plan and final_answer
normally once it passes. Standard library only; never edit tests.
