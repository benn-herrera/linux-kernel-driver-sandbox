"""The shape every output's module has, as the generator calls it."""

from typing import Protocol

from api_gen.model import Api


class Emitter(Protocol):
    """An output module: its label, its objections, and its text. A new emitter starts as
    a copy of these three signatures; each ignores the keywords it does not use.

    `LABEL` heads each of its objections. `validate` returns every objection the output
    has to `api`, each prefixed `<LABEL>: `, and `emit` renders the output's text from an
    `api` its `validate` accepted, `library` being the resolved one the Lua module loads."""

    LABEL: str

    def validate(self, api: Api) -> list[str]: ...

    def emit(self, api: Api, *, source_name: str, stem: str, library: str | None) -> str: ...
