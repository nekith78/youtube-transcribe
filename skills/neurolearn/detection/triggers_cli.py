"""CLI sub-group for managing ~/.neurolearn/triggers.toml.

Usage:
  neurolearn triggers init [--force]
  neurolearn triggers add --universal "p1; p2"
  neurolearn triggers add --raw "p1"
  neurolearn triggers add --soft|--strict --lang <code> "p1"
  neurolearn triggers list [--section <name>]
  neurolearn triggers remove --universal "phrase"
  ...
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import click
import tomlkit
from rich.console import Console
from rich.table import Table

DEFAULT_PATH = Path.home() / ".neurolearn" / "triggers.toml"

_SPLIT_RE = re.compile(r"[;,]")

console = Console()


def _user_path() -> Path:
    """Read from env (testing) or default."""
    p = os.environ.get("YOUTUBE_TRANSCRIBE_TRIGGERS_PATH")
    return Path(p) if p else DEFAULT_PATH


def _split_phrases(s: str) -> list[str]:
    return [p.strip() for p in _SPLIT_RE.split(s) if p.strip()]


def _atomic_write(path: Path, doc: tomlkit.TOMLDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def _load_doc(path: Path) -> tomlkit.TOMLDocument:
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def _stub_doc() -> tomlkit.TOMLDocument:
    """Empty user triggers file with comments and empty sections."""
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Custom triggers — extends built-in defaults."))
    doc.add(tomlkit.comment("See spec §4 for format. Edit via `neurolearn triggers add`."))
    doc.add(tomlkit.nl())

    triggers = tomlkit.table(is_super_table=True)
    triggers["universal"] = tomlkit.table()
    triggers["universal"]["phrases"] = tomlkit.array()
    triggers["raw"] = tomlkit.table()
    triggers["raw"]["phrases"] = tomlkit.array()
    doc["triggers"] = triggers
    return doc


def _ensure_section(doc: tomlkit.TOMLDocument, *path: str) -> tomlkit.items.Item:
    """Drill into doc.triggers.<a>.<b>... creating tables as needed."""
    if "triggers" not in doc:
        doc["triggers"] = tomlkit.table(is_super_table=True)
    cur = doc["triggers"]
    for key in path:
        if key not in cur:
            cur[key] = tomlkit.table()
        cur = cur[key]
    return cur


def _phrases_array(parent: tomlkit.items.Item, key: str) -> tomlkit.items.Array:
    if key not in parent:
        parent[key] = tomlkit.array()
    return parent[key]


def _array_contains(arr: tomlkit.items.Array, phrase: str) -> bool:
    for item in arr:
        if isinstance(item, str) and item == phrase:
            return True
        if isinstance(item, list) and len(item) >= 1 and item[0] == phrase:
            return True
    return False


# === Click group ===


@click.group(name="triggers")
def triggers_cli():
    """Manage ~/.neurolearn/triggers.toml."""


@triggers_cli.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing file.")
def cmd_init(force: bool):
    path = _user_path()
    if path.exists() and not force:
        click.echo(f"Error: {path} already exists. Use --force to overwrite.", err=True)
        raise click.exceptions.Exit(1)
    _atomic_write(path, _stub_doc())
    click.echo(f"Created {path}")


@triggers_cli.command("add")
@click.option("--universal", "section", flag_value="universal")
@click.option("--raw", "section", flag_value="raw")
@click.option("--soft", "section", flag_value="soft")
@click.option("--strict", "section", flag_value="strict")
@click.option("--lang", "lang", default=None, help="ISO code for --soft/--strict.")
@click.argument("phrases", nargs=-1, required=True)
def cmd_add(section: str, lang: str | None, phrases: tuple[str, ...]):
    if section is None:
        click.echo("Error: pass one of --universal/--raw/--soft/--strict", err=True)
        raise click.exceptions.Exit(1)
    if section in ("soft", "strict") and not lang:
        click.echo(f"Error: --{section} requires --lang <code>", err=True)
        raise click.exceptions.Exit(1)

    parsed: list[str] = []
    for chunk in phrases:
        parsed.extend(_split_phrases(chunk))
    if not parsed:
        click.echo("Error: no non-empty phrases parsed", err=True)
        raise click.exceptions.Exit(1)

    path = _user_path()
    doc = _load_doc(path)
    if "triggers" not in doc:
        doc.update(_stub_doc())

    if section == "universal":
        target = _ensure_section(doc, "universal")
        arr = _phrases_array(target, "phrases")
    elif section == "raw":
        target = _ensure_section(doc, "raw")
        arr = _phrases_array(target, "phrases")
    else:  # soft / strict
        target = _ensure_section(doc, "languages", lang)
        arr = _phrases_array(target, section)

    added = 0
    for phrase in parsed:
        if _array_contains(arr, phrase):
            click.echo(f"  • '{phrase}' already exists, skipped")
            continue
        arr.append(phrase)
        added += 1
        click.echo(f"  + '{phrase}'")

    _atomic_write(path, doc)
    click.echo(f"Added {added} phrase(s) to [{section}].")


@triggers_cli.command("remove")
@click.option("--universal", "section", flag_value="universal")
@click.option("--raw", "section", flag_value="raw")
@click.option("--soft", "section", flag_value="soft")
@click.option("--strict", "section", flag_value="strict")
@click.option("--lang", "lang", default=None)
@click.argument("phrase")
def cmd_remove(section: str, lang: str | None, phrase: str):
    path = _user_path()
    doc = _load_doc(path)
    if "triggers" not in doc:
        click.echo("No triggers file. Run `triggers init` first.", err=True)
        raise click.exceptions.Exit(1)
    if section in ("soft", "strict") and not lang:
        click.echo(f"Error: --{section} requires --lang", err=True)
        raise click.exceptions.Exit(1)

    if section == "universal":
        arr = doc["triggers"].get("universal", {}).get("phrases", [])
    elif section == "raw":
        arr = doc["triggers"].get("raw", {}).get("phrases", [])
    else:
        arr = doc["triggers"].get("languages", {}).get(lang, {}).get(section, [])

    new_items = [
        item for item in arr
        if not (isinstance(item, str) and item == phrase)
        and not (isinstance(item, list) and len(item) >= 1 and item[0] == phrase)
    ]
    if len(new_items) == len(arr):
        click.echo(f"'{phrase}' not found in [{section}]", err=True)
        raise click.exceptions.Exit(1)

    arr.clear()
    for item in new_items:
        arr.append(item)
    _atomic_write(path, doc)
    click.echo(f"Removed '{phrase}' from [{section}]")


@triggers_cli.command("list")
@click.option("--section", "filter_section", default=None)
def cmd_list(filter_section: str | None):
    from skills.neurolearn.detection.triggers import load_triggers

    path = _user_path()
    cfg = load_triggers(user_path=path if path.exists() else None)
    table = Table(title="Triggers", show_lines=False)
    table.add_column("Section")
    table.add_column("Phrase")
    table.add_column("Weight", justify="right")

    def _add_section(name: str, items: dict[str, float]):
        for phrase, weight in sorted(items.items()):
            tag = "weighted" if weight != 1.0 else ""
            table.add_row(name, phrase, f"{weight}{' <-' if tag else ''}")

    if filter_section in (None, "universal"):
        _add_section("universal", cfg.universal)
    if filter_section in (None, "raw"):
        _add_section("raw", cfg.raw)
    for lang, lcfg in cfg.languages.items():
        if filter_section in (None, f"soft:{lang}"):
            _add_section(f"soft:{lang}", lcfg.soft)
        if filter_section in (None, f"strict:{lang}"):
            _add_section(f"strict:{lang}", lcfg.strict)

    console.print(table)


import shutil
import subprocess


@triggers_cli.command("reset")
@click.option("--universal", "section", flag_value="universal")
@click.option("--raw", "section", flag_value="raw")
@click.option("--all", "section", flag_value="all")
def cmd_reset(section: str | None):
    path = _user_path()
    if not path.exists():
        click.echo("Nothing to reset.")
        return
    if section == "all":
        path.unlink()
        click.echo(f"Removed {path}")
        return
    doc = _load_doc(path)
    if section == "universal":
        if "triggers" in doc and "universal" in doc["triggers"]:
            doc["triggers"]["universal"]["phrases"] = tomlkit.array()
        click.echo("Cleared [triggers.universal].")
    elif section == "raw":
        if "triggers" in doc and "raw" in doc["triggers"]:
            doc["triggers"]["raw"]["phrases"] = tomlkit.array()
        click.echo("Cleared [triggers.raw].")
    else:
        click.echo("Use --universal, --raw, or --all.", err=True)
        raise click.exceptions.Exit(1)
    _atomic_write(path, doc)


@triggers_cli.command("edit")
def cmd_edit():
    path = _user_path()
    if not path.exists():
        click.echo(f"{path} doesn't exist. Run `triggers init` first.", err=True)
        raise click.exceptions.Exit(1)

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy(path, backup)

    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([editor, str(path)], check=False)
        # Validate after edit
        from skills.neurolearn.detection.triggers import _load_toml
        try:
            _load_toml(path)
        except Exception as e:
            click.echo(f"Invalid TOML after edit: {e}", err=True)
            click.echo(f"Restoring backup from {backup}")
            shutil.copy(backup, path)
            raise click.exceptions.Exit(1)
    finally:
        if backup.exists():
            backup.unlink()
    click.echo("OK.")


@triggers_cli.command("test")
@click.argument("text")
def cmd_test(text: str):
    """Run text through matcher and report which trigger fired."""
    from skills.neurolearn.detection.matcher import match_segment
    from skills.neurolearn.detection.triggers import load_triggers

    path = _user_path()
    cfg = load_triggers(user_path=path if path.exists() else None)
    m = match_segment(text, cfg)
    if m is None:
        click.echo("No trigger matched.")
        return
    click.echo(f"Matched: phrase='{m.phrase}', reason={m.reason}, "
               f"score={m.score:.3f}, weight={m.weight}")


@triggers_cli.group("weight")
def weight_group():
    """Manage per-phrase weights."""


def _find_phrase_in_array(arr, phrase: str) -> int | None:
    for idx, item in enumerate(arr):
        if isinstance(item, str) and item == phrase:
            return idx
        if isinstance(item, list) and len(item) >= 1 and item[0] == phrase:
            return idx
    return None


def _resolve_arr(doc, section: str, lang: str | None):
    if section == "universal":
        return doc["triggers"]["universal"]["phrases"]
    if section == "raw":
        return doc["triggers"]["raw"]["phrases"]
    return doc["triggers"]["languages"][lang][section]


def _parse_weight_args(args: tuple[str, ...]) -> list[tuple[str, float]]:
    """Two forms:
      ("function", "1.5")          → [("function", 1.5)]
      ("function:1.5; class:1.5",) → [("function", 1.5), ("class", 1.5)]
    """
    if len(args) == 2:
        return [(args[0], float(args[1]))]
    if len(args) == 1:
        out = []
        for chunk in _SPLIT_RE.split(args[0]):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" not in chunk:
                raise ValueError(f"Batch entry must be 'phrase:weight', got '{chunk}'")
            phrase, w = chunk.rsplit(":", 1)
            out.append((phrase.strip(), float(w.strip())))
        return out
    raise ValueError("Pass 'phrase value' or batch 'phrase:value;...'")


@weight_group.command("set")
@click.option("--universal", "section", flag_value="universal")
@click.option("--raw", "section", flag_value="raw")
@click.option("--soft", "section", flag_value="soft")
@click.option("--strict", "section", flag_value="strict")
@click.option("--lang", "lang", default=None)
@click.argument("args", nargs=-1, required=True)
def cmd_weight_set(section: str, lang: str | None, args: tuple[str, ...]):
    if section is None:
        click.echo("Pass --universal/--raw/--soft/--strict", err=True)
        raise click.exceptions.Exit(1)
    if section in ("soft", "strict") and not lang:
        click.echo(f"--{section} requires --lang", err=True)
        raise click.exceptions.Exit(1)

    pairs = _parse_weight_args(args)
    path = _user_path()
    doc = _load_doc(path)
    arr = _resolve_arr(doc, section, lang)

    for phrase, weight in pairs:
        if not 0.1 <= weight <= 5.0:
            click.echo(f"Warning: suspicious weight {weight} for '{phrase}'")
        idx = _find_phrase_in_array(arr, phrase)
        if idx is None:
            click.echo(f"'{phrase}' not in [{section}]", err=True)
            continue
        new_entry = tomlkit.array()
        new_entry.append(phrase)
        new_entry.append(weight)
        arr[idx] = new_entry
        click.echo(f"  {phrase} → weight {weight}")

    _atomic_write(path, doc)


@weight_group.command("unset")
@click.option("--universal", "section", flag_value="universal")
@click.option("--raw", "section", flag_value="raw")
@click.option("--soft", "section", flag_value="soft")
@click.option("--strict", "section", flag_value="strict")
@click.option("--lang", "lang", default=None)
@click.argument("phrase")
def cmd_weight_unset(section: str, lang: str | None, phrase: str):
    path = _user_path()
    doc = _load_doc(path)
    arr = _resolve_arr(doc, section, lang)
    idx = _find_phrase_in_array(arr, phrase)
    if idx is None:
        click.echo(f"'{phrase}' not in [{section}]", err=True)
        raise click.exceptions.Exit(1)
    arr[idx] = phrase
    _atomic_write(path, doc)
    click.echo(f"  {phrase} → weight 1.0 (reverted)")


@weight_group.command("list")
def cmd_weight_list():
    """Show only non-default weights."""
    from skills.neurolearn.detection.triggers import load_triggers

    path = _user_path()
    cfg = load_triggers(user_path=path if path.exists() else None)
    found = False

    def _show(name: str, items: dict[str, float]):
        nonlocal found
        for phrase, w in items.items():
            if w != 1.0:
                click.echo(f"  [{name}] '{phrase}' → {w}")
                found = True

    _show("universal", cfg.universal)
    _show("raw", cfg.raw)
    for lang, lcfg in cfg.languages.items():
        _show(f"soft:{lang}", lcfg.soft)
        _show(f"strict:{lang}", lcfg.strict)

    if not found:
        click.echo("No non-default weights set.")
