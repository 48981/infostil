#!/usr/bin/env python3
"""Просмотр и удаление невидимых знаков в тексте.

  chistka.py файл             — показать: строка · позиция · код · имя · действие · контекст
  chistka.py файл --fix       — удалить, результат в файл (оригинал → файл.bak)
  chistka.py - < текст        — читать stdin, показать
  chistka.py - --fix < в > из — очищенный текст в stdout

Удаляет: нулевой ширины (U+200B..200D), метки и управляющие направлением (200E, 200F,
202A..202E, 2066..2069), невидимые операторы (2060..2064), BOM (FEFF), мягкий перенос (00AD),
теги (E0000..E007F), пустые «буквы»-заполнители, прочие управляющие и форматные знаки.
Не трогает: ZWJ, селекторы вариантов и теги внутри эмодзи; ZWJ/ZWNJ и метки направления
в арабском, иврите и индийских письменностях, где они часть орфографии.
Только показывает: неразрывные и узкие пробелы (в русской типографике они законны),
знаки частного использования и знаки, которых нет в базе Unicode этой версии Python.
Статистическую метку в подборе слов (водяной знак OpenAI textGrain и подобные) эта чистка
не видит и не снимает: её нет в знаках, она в выборе слов.
"""
import shutil
import sys
import unicodedata

ZW_JOINERS = {0x200C, 0x200D}
BIDI_MARKS = {0x200E, 0x200F, 0x061C}
REMOVE = {0x200B, 0xFEFF, 0x00AD, 0x180E, 0x034F, 0x3164, 0xFFA0, 0x115F, 0x1160, 0x2800} \
    | set(range(0x202A, 0x202F)) | set(range(0x2060, 0x2065)) | set(range(0x2066, 0x2070)) \
    | set(range(0xFFF9, 0xFFFC))
TAGS = range(0xE0000, 0xE0080)
VARIATION = {0xFE0E, 0xFE0F}
SHOW_SPACES = {0x00A0, 0x202F, 0x2009, 0x2007, 0x2008, 0x200A, 0x2002, 0x2003, 0x3000}
# форматные знаки, которые в своих письменностях видимы и нужны (арабские числовые знаки и т. п.)
VISIBLE_CF = set(range(0x0600, 0x0606)) | {0x06DD, 0x070F, 0x0890, 0x0891, 0x08E2, 0x110BD, 0x110CD}


def is_emoji(ch):
    if not ch:
        return False
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF or 0x2190 <= o <= 0x2BFF
            or o in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299))


def is_joining_script(ch):
    """Письменности, где ZWJ/ZWNJ и метки направления — часть орфографии."""
    if not ch:
        return False
    o = ord(ch)
    return 0x0590 <= o <= 0x08FF or 0x0900 <= o <= 0x0DFF or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFC


def in_emoji_tag_run(text, i):
    """Тег-знак после чёрного флага U+1F3F4 — часть эмодзи-флага (Англия, Шотландия, Уэльс)."""
    j = i - 1
    while j >= 0 and ord(text[j]) in TAGS:
        j -= 1
    return j >= 0 and ord(text[j]) == 0x1F3F4


def scan(text):
    """Список (индекс, знак, действие): 'del' — удалить, 'show' — только показать."""
    out = []
    n = len(text)
    for i, ch in enumerate(text):
        o = ord(ch)
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < n else ""
        if o < 0x80 and (o >= 0x20 or ch in "\n\r\t"):
            continue
        if o in VARIATION:
            if is_emoji(prev) or prev in ("#", "*") or (prev.isascii() and prev.isdigit()):
                continue
            out.append((i, ch, "del"))
        elif o in ZW_JOINERS:
            if o == 0x200D and (is_emoji(prev) or ord(prev or " ") in VARIATION or 0x1F3FB <= ord(prev or " ") <= 0x1F3FF) and is_emoji(nxt):
                continue
            if is_joining_script(prev):
                continue
            out.append((i, ch, "del"))
        elif o in BIDI_MARKS:
            if is_joining_script(prev) or is_joining_script(nxt):
                continue
            out.append((i, ch, "del"))
        elif o in TAGS:
            if in_emoji_tag_run(text, i):
                continue
            out.append((i, ch, "del"))
        elif o in REMOVE:
            out.append((i, ch, "del"))
        elif o in SHOW_SPACES:
            out.append((i, ch, "show"))
        else:
            cat = unicodedata.category(ch)
            if cat == "Cc" or (cat == "Cf" and o not in VISIBLE_CF):
                out.append((i, ch, "del"))
            elif cat in ("Co", "Cn", "Zs") or cat in ("Zl", "Zp"):
                out.append((i, ch, "show"))
    return out


def report(text, hits):
    for i, ch, act in hits:
        line = text.count("\n", 0, i) + 1
        ctx = (text[max(0, i - 12):i] + "⟦⟧" + text[i + 1:i + 12]).replace("\r", "").replace("\n", "⏎")
        name = unicodedata.name(ch, "БЕЗ ИМЕНИ")
        what = "удалить" if act == "del" else "оставить"
        print(f"стр {line:>4} · поз {i:>6} · U+{ord(ch):04X} · {name} · {what} · {ctx}")
    d = sum(1 for h in hits if h[2] == "del")
    print(f"\nНайдено: {len(hits)} (к удалению {d}, только показано {len(hits) - d}). Длина текста: {len(text)} знаков.")


def clean(text, hits):
    drop = {i for i, _, a in hits if a == "del"}
    return "".join(c for i, c in enumerate(text) if i not in drop)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if a != "--fix"]
    fix = "--fix" in sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    src = args[0]
    try:
        if src == "-":
            text = sys.stdin.buffer.read().decode("utf-8")
        else:
            # newline="" — переводы строк читаем и пишем как есть, CRLF не превращаем в LF
            with open(src, encoding="utf-8", newline="") as f:
                text = f.read()
    except UnicodeDecodeError as e:
        print(f"Файл не в UTF-8, чистка не выполнена: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Не удалось прочитать файл: {e}", file=sys.stderr)
        return 1
    hits = scan(text)
    if not fix:
        if hits:
            report(text, hits)
        else:
            print("Невидимых знаков не найдено.")
        return 0
    res = clean(text, hits)
    removed = len(text) - len(res)
    if src == "-":
        sys.stdout.buffer.write(res.encode("utf-8"))
        print(f"Удалено знаков: {removed}", file=sys.stderr)
    elif removed:
        shutil.copy2(src, src + ".bak")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(res)
        print(f"Удалено знаков: {removed}; оригинал в {src}.bak")
    else:
        print("Удалено знаков: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
