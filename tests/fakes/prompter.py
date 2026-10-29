"""A prompter that answers from a script and records what it was asked."""

from collections.abc import Sequence

from huron.applications.cli.prompts import Validate


class ScriptedPrompter:
    """Pops answers in order; an answer ``validate`` rejects is recorded and the next one used."""

    def __init__(self, answers: Sequence[object] = ()) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []
        self.rejected: list[tuple[str, str]] = []

    def text(self, message: str, default: str = "", validate: Validate | None = None) -> str:
        while True:
            answer = self._next(message)
            value = default if answer is None else str(answer)
            problem = None if validate is None else validate(value)
            if problem is None:
                return value
            self.rejected.append((value, problem))

    def select(self, message: str, choices: Sequence[str], default: str | None = None) -> str:
        answer = self._next(message)
        value = default if answer is None else str(answer)
        assert value in choices, f"{value!r} is not one of {choices}"
        return value

    def confirm(self, message: str, default: bool = False) -> bool:
        answer = self._next(message)
        return default if answer is None else bool(answer)

    def _next(self, message: str) -> object:
        self.asked.append(message)
        assert self.answers, f"no scripted answer for {message!r}"
        return self.answers.pop(0)
