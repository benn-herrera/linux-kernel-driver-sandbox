"""The shape every output's module has, as the generator calls it."""

from pathlib import Path
from typing import Protocol

from api_gen.model import Api


class ToolError(Exception):
    """An external tool an `emit` runs is missing or failed; the message says which and
    why, for the generator to report."""


class Emitter(Protocol):
    """An output module: its label, its objections, its path and its text. A new emitter
    starts as a copy of these four signatures; each ignores the keywords it does not use.

    `LABEL` heads each of its objections. `validate` returns every objection the output
    has to `api`, each prefixed `<LABEL>: `. `output_path` is where the output lands,
    relative to the generated directory. `emit` renders the output's text from an `api`
    its `validate` accepted, `library` being the resolved one the Lua module loads and the
    Rust binding links and `project` the project's name, its directory's, and raises
    `ToolError` when a tool it runs is missing or fails."""

    LABEL: str

    def validate(self, api: Api) -> list[str]: ...

    def output_path(self, *, name: str, project: str) -> Path: ...

    def emit(self, api: Api, *, source_name: str, name: str, library: str | None, project: str) -> str: ...
