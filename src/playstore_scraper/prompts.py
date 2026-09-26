"""Interactive menus for count / sort / language."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.prompt import Prompt

from playstore_scraper.config import (
    InvalidCountError,
    InvalidSortError,
    parse_count,
    parse_sort,
)
from playstore_scraper.input_parser import (
    AppInput,
    InvalidAppInputError,
    resolve_app_input,
)
from playstore_scraper.languages import InvalidLanguageError, parse_langs

console = Console(stderr=True)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def prompt_app_input(existing: str | None) -> AppInput:
    if existing:
        return resolve_app_input(existing)
    if not _is_interactive():
        raise InvalidAppInputError(
            "App package name or URL is required in non-interactive mode."
        )
    while True:
        value = Prompt.ask("App package name or Play Store URL").strip()
        try:
            return resolve_app_input(value)
        except InvalidAppInputError as exc:
            console.print(f"[red]{exc}[/red]")


def prompt_count(existing: str | None, *, yes: bool) -> str:
    if existing is not None:
        return existing
    if yes or not _is_interactive():
        return "all"

    console.print("\n[bold]How many reviews?[/bold]")
    console.print(
        "  1) 100   2) 1,000   3) 10,000   4) 100,000   5) All possible   6) Custom number"
    )
    choice = Prompt.ask("Choose", default="5").strip()
    mapping = {"1": "100", "2": "1000", "3": "10000", "4": "100000", "5": "all"}
    if choice in mapping:
        return mapping[choice]
    if choice == "6":
        while True:
            custom = Prompt.ask("Enter number").strip()
            try:
                n = parse_count(custom)
                return "all" if n is None else str(n)
            except InvalidCountError as exc:
                console.print(f"[red]{exc}[/red]")
    try:
        parse_count(choice)
        return choice
    except InvalidCountError:
        console.print("[yellow]Using default: all[/yellow]")
        return "all"


def prompt_sort(existing: str | None, *, yes: bool) -> str:
    if existing is not None:
        return existing
    if yes or not _is_interactive():
        return "newest"

    console.print("\n[bold]Sort by?[/bold]")
    console.print(
        "  1) Newest   2) Most relevant   3) Rating   4) All sorts (max coverage)"
    )
    choice = Prompt.ask("Choose", default="1").strip().lower()
    mapping = {
        "1": "newest",
        "2": "relevant",
        "3": "rating",
        "4": "all",
        "newest": "newest",
        "relevant": "relevant",
        "rating": "rating",
        "all": "all",
    }
    if choice in mapping:
        return mapping[choice]
    try:
        return parse_sort(choice)
    except InvalidSortError:
        console.print("[yellow]Using default: newest[/yellow]")
        return "newest"


def prompt_lang(
    existing: str | None,
    *,
    yes: bool,
    url_lang: str | None = None,
) -> str:
    if existing is not None:
        return existing
    if yes:
        return url_lang or "en"
    if not _is_interactive():
        return url_lang or "en"

    console.print("\n[bold]Review language?[/bold]")
    console.print(
        "  1) English (en)   2) Any language   3) Hindi (hi)   4) Other (type code or name)"
    )
    choice = Prompt.ask("Choose", default="1").strip().lower()
    if choice in {"1", "en", "english"}:
        return "en"
    if choice in {"2", "any", "all"}:
        return "any"
    if choice in {"3", "hi", "hindi"}:
        return "hi"
    if choice == "4":
        while True:
            other = Prompt.ask(
                "Language code or name (e.g. de, german, en,hi)"
            ).strip()
            try:
                parse_langs(other)
                return other
            except InvalidLanguageError as exc:
                console.print(f"[red]{exc}[/red]")
    try:
        parse_langs(choice)
        return choice
    except InvalidLanguageError:
        console.print("[yellow]Using default: en[/yellow]")
        return "en"


def resolve_user_options(
    *,
    app: str | None,
    count: str | None,
    sort: str | None,
    lang: str | None,
    yes: bool,
) -> tuple[str, str, str, str]:
    """Return (app_id, count_str, sort_str, lang_str)."""
    app_input = prompt_app_input(app)
    count_str = prompt_count(count, yes=yes)
    sort_str = prompt_sort(sort, yes=yes)
    lang_str = prompt_lang(lang, yes=yes, url_lang=app_input.lang_from_url)

    parse_count(count_str)
    parse_sort(sort_str)
    parse_langs(lang_str)

    return app_input.app_id, count_str, sort_str, lang_str
