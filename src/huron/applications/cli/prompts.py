"""Interactive prompts behind a protocol, so walkthroughs can be scripted in tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

import questionary

from huron.applications.cli.errors import CliError, ExitCode

__all__ = ["Prompter", "QuestionaryPrompter", "Validate"]

type Validate = Callable[[str], str | None]


class Prompter(Protocol):
    """Asks the user questions. ``validate`` returns an error message or ``None``."""

    def text(self, message: str, default: str = "", validate: Validate | None = None) -> str:
        """A line of text."""
        ...

    def select(self, message: str, choices: Sequence[str], default: str | None = None) -> str:
        """One of ``choices``."""
        ...

    def confirm(self, message: str, default: bool = False) -> bool:
        """Yes or no."""
        ...


class QuestionaryPrompter:
    """Prompts in the terminal with questionary."""

    def text(self, message: str, default: str = "", validate: Validate | None = None) -> str:
        """A line of text, re-asked until ``validate`` accepts it."""
        checker = None if validate is None else (lambda value: validate(value) or True)
        return _answer(questionary.text(message, default=default, validate=checker).ask())

    def select(self, message: str, choices: Sequence[str], default: str | None = None) -> str:
        """One of ``choices``."""
        return _answer(questionary.select(message, choices=list(choices), default=default).ask())

    def confirm(self, message: str, default: bool = False) -> bool:
        """Yes or no."""
        answer = questionary.confirm(message, default=default).ask()
        if answer is None:
            raise CliError("cancelled", ExitCode.INTERRUPTED)
        return bool(answer)


def _answer(value: object) -> str:
    if value is None:
        raise CliError("cancelled", ExitCode.INTERRUPTED)
    return str(value)
