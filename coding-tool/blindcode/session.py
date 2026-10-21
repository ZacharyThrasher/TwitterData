"""Interactive terminal coding session for one human coder.

The coder sees the thread context and reply text, nothing else. Their own
items come in a per-coder shuffled order and the session resumes where they
stopped. Input and output are injectable so the loop is testable.
"""
from __future__ import annotations

from typing import Callable

from .codebook import Codebook, CodebookError, Field
from .items import Item, coder_order
from .store import CoderStore

HELP = "Keys: number or value to answer | ? definition | b back one field | s skip item | q save and quit"


class _Quit(Exception):
    pass


class _Skip(Exception):
    pass


def _prompt_line(f: Field) -> str:
    if f.type == "binary":
        return f"{f.name} [0/1]: "
    if f.type == "categorical":
        opts = "  ".join(f"{i}={o}" for i, o in enumerate(f.options, 1))
        return f"{f.name}  {opts}\n> "
    return f"{f.name} (optional, max {f.max_words or 'any'} words, Enter to leave blank): "


def _interpret(f: Field, raw: str) -> str:
    s = raw.strip()
    if f.type == "categorical" and s.isdigit() and 1 <= int(s) <= len(f.options):
        return f.options[int(s) - 1]
    return f.normalise(s)


def code_item(item: Item, codebook: Codebook, ask: Callable[[str], str], say: Callable[[str], None]) -> dict:
    values: dict[str, str] = {}
    fields = list(codebook.fields)
    i = 0
    while i < len(fields):
        f = fields[i]
        raw = ask(_prompt_line(f))
        cmd = raw.strip().lower()
        if cmd == "q":
            raise _Quit
        if cmd == "s":
            raise _Skip
        if cmd == "?":
            say(f"  {f.name}: {f.definition}")
            continue
        if cmd == "b":
            i = max(0, i - 1)
            continue
        try:
            values[f.name] = _interpret(f, raw)
        except CodebookError as e:
            say(f"  Not valid: {e}")
            continue
        i += 1
    return values


def run_session(items: list[Item], codebook: Codebook, store: CoderStore, *,
                ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> dict:
    """Code every not-yet-coded item. Returns counts."""
    done = set(store.latest())
    todo = [it for it in coder_order(items, store.coder) if it.uid not in done]
    counts = {"saved": 0, "skipped": 0, "remaining": len(todo)}
    say(f"Coder {store.coder}: {len(done)} of {len(items)} done, {len(todo)} to go.")
    say(HELP)
    for n, item in enumerate(todo, 1):
        say("")
        say("=" * 60)
        say(f"Item {len(done) + n} of {len(items)}")
        if item.context:
            say(f"Context: {codebook.contexts.get(item.context, item.context)}")
        say("-" * 60)
        say(item.text)
        say("-" * 60)
        try:
            while True:
                values = code_item(item, codebook, ask, say)
                say("  " + ", ".join(f"{k}={v}" for k, v in values.items() if v != ""))
                if ask("Enter to save, r to redo: ").strip().lower() != "r":
                    break
        except _Skip:
            counts["skipped"] += 1
            continue
        except _Quit:
            break
        store.save(item.uid, values, codebook)
        counts["saved"] += 1
        counts["remaining"] -= 1
    say(f"Saved {counts['saved']} this session. {counts['remaining']} left.")
    return counts
