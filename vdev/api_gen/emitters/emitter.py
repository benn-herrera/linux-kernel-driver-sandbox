"""The shape every output's module has, as the generator calls it."""

from pathlib import Path
from typing import Protocol

from api_gen.model import Api


class Emitter(Protocol):
    """An output module: its label, its objections, its path and its text. A new emitter
    starts as a copy of these four signatures; each ignores the keywords it does not use.

    `LABEL` heads each of its objections. `validate` returns every objection the output
    has to `api`, each prefixed `<LABEL>: `. `output_path` is where the output lands,
    relative to the generated directory. `emit` renders the output's text from an `api`
    its `validate` accepted, `library` being the resolved one the Lua module loads."""

    LABEL: str

    def validate(self, api: Api) -> list[str]: ...

    def output_path(self, *, stem: str, exercise: str) -> Path: ...

    def emit(self, api: Api, *, source_name: str, stem: str, library: str | None) -> str: ...
