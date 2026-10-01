"""Load, validate and normalise an .adef.toml API definition.

Parameter and field order is document order. The loader relies on `tomllib`
building insertion-ordered dicts, so iterating a table yields its keys in the
order they appear in the file.
"""

import re
import tomllib
from collections.abc import Callable, Container, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from api_gen import naming

BUILTIN_TYPES = frozenset({*naming.BUILTIN_C_TYPES, "memory"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_LOWERCASE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")
_LITERAL_TERM = re.compile(r"(-?)(?:0x([0-9a-fA-F]+)|([0-9]+))\Z")
FORMATS = ("dec", "hex")
REFS = ("in", "out", "inout")
TABLES = frozenset(
    {"_general", "untyped_bit_const", "untyped_const", "string_const", "typed_const", "opaque_ref", "boxed_scalar",
     "struct", "function", "_wrapped_api"}
)
GROUP_PROPERTIES = frozenset({"_docstring", "_base_type", "_to_string"})
STRING_GROUP_PROPERTIES = frozenset({"_docstring"})  # a string constant has no fixed-width representation
OPAQUE_PROPERTIES = frozenset({"_docstring", "_class", "_ctor", "_dtor"})
BOXED_PROPERTIES = frozenset({"_docstring", "_base_type"})
CONST_ATTRIBUTES = frozenset({"_value", "_docstring", "_format"})
FIELD_ATTRIBUTES = frozenset({"_type", "_docstring"})
PARAM_ATTRIBUTES = frozenset({"_type", "_ref", "_count", "_optional", "_docstring"})
COUNT_TYPES = ("u8", "u16", "u32", "u64")
FLOAT_TYPES = ("f32", "f64")
INTEGER_TYPES = tuple(t for t in naming.BUILTIN_C_TYPES if t not in FLOAT_TYPES)  # a boxed scalar's _base_type


class DefinitionError(Exception):
    """The definition cannot be turned into an API."""

    def objections(self) -> tuple["DefinitionError", ...]:
        """Each objection this error carries, in order: itself alone."""
        return (self,)


class NotImplementedDefinition(DefinitionError):
    """The definition says something the format allows and the generator cannot produce yet."""


class DefinitionErrors(DefinitionError):
    """Several objections to one definition, in the document order of the items they concern."""

    def __init__(self, errors: Sequence[DefinitionError]) -> None:
        super().__init__("\n".join(str(e) for e in errors))
        self.errors = tuple(errors)

    def objections(self) -> tuple[DefinitionError, ...]:
        return self.errors


# The item an objection's `where` names: its table, then an array index or a name.
_WHERE = re.compile(r"(\w+)(?:\[(\d+)\])?(?:\.(\w+))?")
T = TypeVar("T")


class _Objections:
    """The loader's objections, collected item by item and raised together at the end,
    ordered by where each item stands in `data`. Without `data`, they keep the order found,
    which is document order for one item's own members."""

    def __init__(self, data: Mapping | None = None) -> None:
        self._data = data if data is not None else {}
        self._found: list[tuple[tuple[int, int], DefinitionError]] = []
        self.failed: set[str] = set()  # the `where` of every item that drew an objection

    @contextmanager
    def item(self, where: str) -> Iterator[None]:
        """Runs the block as the item at `where`, recording a `DefinitionError` it raises."""
        try:
            yield
        except DefinitionError as e:
            self.record(e, where)

    def record(self, error: DefinitionError, where: str) -> None:
        self.failed.add(where)
        position = self._position(where)
        self._found += [(position, e) for e in error.objections()]

    def raise_any(self) -> None:
        """Raises what was recorded: a lone objection as itself, several as `DefinitionErrors`."""
        errors = [e for _, e in sorted(self._found, key=lambda found: found[0])]
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise DefinitionErrors(errors)

    def _position(self, where: str) -> tuple[int, int]:
        """(the table's position among the top-level tables, the item's within that table)
        for `where` such as `function.open_port.unit`, `untyped_const[1]` or
        `untyped_bit_const.feat_a`, an entry of an array table standing where its group does."""
        match = _WHERE.match(where)
        assert match is not None  # every where begins with its table's name
        category, index, name = match.groups()
        tables = list(self._data)
        if category not in tables:
            return len(tables), 0
        table = self._data[category]
        if index is not None:
            item = int(index)
        elif isinstance(table, dict) and name in table:
            item = list(table).index(name)
        elif isinstance(table, list):
            item = next((i for i, group in enumerate(table) if isinstance(group, dict) and name in group), 0)
        else:
            item = 0
        return tables.index(category), item


@dataclass(frozen=True, kw_only=True)
class Node:
    """Every item of the tree: its name as the definition writes it, and its docstring."""

    name: str
    docstring: str | None


@dataclass(frozen=True)
class LiteralTerm:
    """A composed entry's literal term, parsed once by the loader."""

    value: int
    format: str  # one of FORMATS: the base the definition wrote it in


# A composed entry's term: the name of an earlier entry, or a literal.
Term = str | LiteralTerm


@dataclass(frozen=True, kw_only=True)
class BitConst(Node):
    """An `untyped_bit_const` entry: a single bit, or a sum of earlier entries and literals."""

    bit: int | None  # set for a single bit
    parts: tuple[Term, ...]  # set for a sum, in the order written
    value: int  # the resolved value: 1 << bit, or the (overlap-checked) sum of parts
    format: str  # one of FORMATS: how a literal of the value is spelled


@dataclass(frozen=True, kw_only=True)
class EnumEntry(Node):
    """An integer constant: a typed enum's entry, or a plain `untyped_const` group's, which
    alone may be a sum."""

    value: int
    format: str  # one of FORMATS
    parts: tuple[Term, ...] = ()  # set for a plain-group sum, in the order written


@dataclass(frozen=True, kw_only=True)
class StringConst(Node):
    value: str  # holds no '"', '\' or control character, so it is a valid C and Lua literal as-is


Entry = TypeVar("Entry", BitConst, EnumEntry, StringConst)


@dataclass(frozen=True, kw_only=True)
class Group(Node, Generic[Entry]):
    """One table of an untyped constant array. A group has no name in the definition,
    so `name` is where it is, `untyped_const[0]`, never an identifier."""

    base_type: str | None  # a key of naming.BASE_C_TYPES; None for a string group
    to_string: str | None  # the conversion function's name; always None for a string group
    entries: tuple[Entry, ...]


def single_bit_entries(group: Group[BitConst]) -> tuple[BitConst, ...]:
    """`group`'s entries whose value has exactly one bit set, in document order: what a bit
    group's conversion decomposes a value into; a multi-bit composed entry is never one."""
    return tuple(c for c in group.entries if c.value > 0 and c.value & (c.value - 1) == 0)


def named_values(group: Group[EnumEntry]) -> tuple[EnumEntry, ...]:
    """One entry per distinct value of a plain group, in the order the values first appear,
    each the later entry where two share a value: what a plain group's conversion names a
    value by. The loader refuses a shared value in an enum, so an enum needs no such step."""
    return tuple({e.value: e for e in group.entries}.values())


@dataclass(frozen=True, kw_only=True)
class TypedConst(Node):
    entries: tuple[EnumEntry, ...]
    base_type: str  # a key of naming.BASE_C_TYPES
    to_string: str | None  # the conversion function's name


@dataclass(frozen=True, kw_only=True)
class OpaqueRef(Node):
    ctor: str | None  # function with exactly one out parameter of this type
    dtor: str | None  # function taking only this type by value; set only with ctor
    class_name: str  # `_class`, lowercase, or else the ref's name; each binding applies its own casing


@dataclass(frozen=True, kw_only=True)
class BoxedScalar(Node):
    base_type: str  # one of INTEGER_TYPES


@dataclass(frozen=True, kw_only=True)
class Field(Node):
    type: str


@dataclass(frozen=True, kw_only=True)
class Struct(Node):
    fields: tuple[Field, ...]


@dataclass(frozen=True, kw_only=True)
class Param(Node):
    """A function parameter, in its function's document order."""

    type: str
    ref: str | None  # one of REFS; None is by value
    count_type: str | None  # memory only, one of COUNT_TYPES: the type of its naming.count_param
    optional: bool  # only with a ref, and on memory only with ref "in"


@dataclass(frozen=True, kw_only=True)
class Function(Node):
    """A function: its `_return` enum's name and its parameters."""

    returns: str
    params: tuple[Param, ...]

    def docs(self) -> list[str]:
        """The function's docstring, if any, followed by each parameter's as `name: text`."""
        docs = [self.docstring] if self.docstring else []
        docs += [f"{p.name}: {p.docstring}" for p in self.params if p.docstring]
        return docs


@dataclass(frozen=True)
class ClassShape:
    """What an object-semantics binding builds for an opaque ref with a `_ctor`, as the
    definition states it."""

    opaque: OpaqueRef
    ctor: Function
    handle: Param  # the ctor's one `out` parameter of the opaque's type
    cached: tuple[Param, ...]  # the ctor's other `out` parameters, each kept on the object
    methods: tuple[Function, ...]  # every other function but the dtor whose first parameter is the opaque by value
    dtor: Function | None

    def class_params(self) -> list[tuple[Function, tuple[Param, ...], bool]]:
        """(function, the parameters the class renders, whether it is the ctor) for the ctor
        and each method: the ctor's every parameter, a method's all but its first, which
        is the handle the object holds. The dtor renders none."""
        return [(self.ctor, self.ctor.params, True), *((fn, fn.params[1:], False) for fn in self.methods)]

    def members(self, own: Iterable[str]) -> list[tuple[str, str]]:
        """(where, name) of every member the class defines: `own`, the members a binding
        generates itself, then each method and each cached `out` under its parameter's name."""
        members = [("the class's own member", name) for name in own]
        members += [(f"function.{fn.name}", fn.name) for fn in self.methods]
        members += [(f"function.{self.ctor.name}.{p.name}", p.name) for p in self.cached]
        return members


@dataclass(frozen=True)
class WrappedApi:
    """`[_wrapped_api]`: the wrapped API, as its C header, which the implementation includes,
    and the constants of this API pinned to that header's macros."""

    header: str  # relative to the project directory
    pins: tuple[tuple[str, str], ...]  # (untyped_bit_const name, the header's macro it equals)


@dataclass(frozen=True)
class Api:
    name: str
    namespace: str
    version: tuple[int, int, int, int]
    library: str | None
    bit_const_groups: tuple[Group[BitConst], ...]
    const_groups: tuple[Group[EnumEntry], ...]
    string_const_groups: tuple[Group[StringConst], ...]
    typed_consts: tuple[TypedConst, ...]
    opaque_refs: tuple[OpaqueRef, ...]
    boxed_scalars: tuple[BoxedScalar, ...]
    structs: tuple[Struct, ...]
    functions: tuple[Function, ...]
    wrapped_api: WrappedApi | None

    @property
    def bit_consts(self) -> tuple[BitConst, ...]:
        """Every untyped_bit_const entry across the groups, in document order."""
        return tuple(c for g in self.bit_const_groups for c in g.entries)

    @property
    def consts(self) -> tuple[EnumEntry, ...]:
        """Every untyped_const entry across the groups, in document order."""
        return tuple(c for g in self.const_groups for c in g.entries)

    @property
    def string_consts(self) -> tuple[StringConst, ...]:
        """Every string_const entry across the groups, in document order."""
        return tuple(c for g in self.string_const_groups for c in g.entries)

    def constant_names(self, *, enum_entries: bool = True, version: bool = False) -> list[tuple[str, str]]:
        """(where, name) for every constant of every kind in document order, typed enum
        entries last unless `enum_entries` is false, and with `version` the version constant
        first: everything that becomes a `naming.const_name`."""
        names = [("the API version constant", naming.VERSION_KEY)] if version else []
        names += [(f"untyped_bit_const.{c.name}", c.name) for c in self.bit_consts]
        names += [(f"untyped_const.{c.name}", c.name) for c in self.consts]
        names += [(f"string_const.{c.name}", c.name) for c in self.string_consts]
        if enum_entries:
            names += [(f"typed_const.{t.name}.{e.name}", e.name) for t in self.typed_consts for e in t.entries]
        return names

    def classes(self) -> tuple[ClassShape, ...]:
        """One shape per opaque ref that names a `_ctor`, in document order."""
        functions = {f.name: f for f in self.functions}
        shapes = []
        for o in self.opaque_refs:
            if o.ctor is None:
                continue
            ctor = functions[o.ctor]
            shapes.append(ClassShape(
                opaque=o,
                ctor=ctor,
                handle=next(p for p in ctor.params if p.type == o.name and p.ref == "out"),
                cached=tuple(p for p in ctor.params if p.ref == "out" and p.type != o.name),
                methods=tuple(
                    f for f in self.functions
                    if f.name not in (o.ctor, o.dtor) and f.params and f.params[0].type == o.name and f.params[0].ref is None
                ),
                dtor=None if o.dtor is None else functions[o.dtor],
            ))
        return tuple(shapes)

    def success_entry(self, fn: Function) -> EnumEntry:
        """The zero-valued entry of `fn`'s return enum, which the loader requires."""
        returns = next(t for t in self.typed_consts if t.name == fn.returns)
        return next(e for e in returns.entries if e.value == 0)

    def kind(self, type_name: str) -> str:
        """One of "builtin", "enum", "opaque", "boxed", "struct" for a validated type name."""
        if type_name in BUILTIN_TYPES:
            return "builtin"
        if any(t.name == type_name for t in self.typed_consts):
            return "enum"
        if any(o.name == type_name for o in self.opaque_refs):
            return "opaque"
        if any(b.name == type_name for b in self.boxed_scalars):
            return "boxed"
        if any(s.name == type_name for s in self.structs):
            return "struct"
        raise KeyError(type_name)

    def names(self) -> list[tuple[str, str]]:
        """(where, name) for every name the definition gives, in document order, `where`
        spelled as the loader's messages spell it: `function.open_port.unit`."""
        names = [("_general._namespace", self.namespace), *self.constant_names()]
        names += [
            (f"{g.name}._to_string", g.to_string)
            for g in (*self.bit_const_groups, *self.const_groups)
            if g.to_string is not None
        ]
        for t in self.typed_consts:
            names.append((f"typed_const.{t.name}", t.name))
            if t.to_string is not None:
                names.append((f"typed_const.{t.name}._to_string", t.to_string))
        for o in self.opaque_refs:
            names += [(f"opaque_ref.{o.name}", o.name), (f"opaque_ref.{o.name}._class", o.class_name)]
        names += [(f"boxed_scalar.{b.name}", b.name) for b in self.boxed_scalars]
        for s in self.structs:
            names.append((f"struct.{s.name}", s.name))
            names += [(f"struct.{s.name}.{f.name}", f.name) for f in s.fields]
        for fn in self.functions:
            names.append((f"function.{fn.name}", fn.name))
            names += [(f"function.{fn.name}.{p.name}", p.name) for p in fn.params]
        return names

    def version_value(self) -> int:
        """The version packed into one 32-bit value, most-significant byte first."""
        shifts = (24, 16, 8, 0)
        return sum(b << s for b, s in zip(self.version, shifts))



def duplicates(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Each name that `pairs`, (what defines it, name), holds more than once, with every
    definer in order, in the order the names are first seen."""
    definers: dict[str, list[str]] = {}
    for definer, name in pairs:
        definers.setdefault(name, []).append(definer)
    return {name: found for name, found in definers.items() if len(found) > 1}


def duplicate_objections(pairs: Iterable[tuple[str, str]], where: str) -> list[str]:
    """One objection per name that `pairs`, (what defines it, name), holds more than once,
    naming everything that defines it, as a binding reports a name it would define twice
    in `where`."""
    return [f"{where}: {n} would be defined more than once, by {' and '.join(s)}" for n, s in duplicates(pairs).items()]


def generated_name_objections(names: Iterable[tuple[str, str]], used: Container[str]) -> list[str]:
    """One objection per (where, name) of `names` whose name is in `used`: a name an output's
    generated code binds or reaches itself where that definition name would be in scope."""
    return [f"{where}: '{name}' is a name the generated code uses" for where, name in names if name in used]


def load(path: Path) -> Api:
    """The definition in the file at `path` as an `Api`; see `from_dict()`."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise DefinitionError(str(e)) from e
    return from_dict(data)


def from_dict(data: Mapping) -> Api:
    """The definition in `data` as an `Api`, else a `DefinitionError` carrying every objection
    found, in the document order of the items they concern (`DefinitionError.objections()`).

    Each top-level item (a constant group, a typed enum, an opaque ref, a boxed scalar, a
    struct, a function, `[_wrapped_api]`) is parsed on its own, as is each field of a struct
    and each parameter and the `_return` of a function, so one mistake does not hide
    another. The checks across items then run over what parsed; one whose subject failed to
    parse is skipped, and a reference to an item that failed reports an unknown name. A
    failure that leaves nothing to parse stops alone: an unknown top-level table, a missing
    or malformed `[_general]`, and in `load()` a file that is not UTF-8 TOML.
    """
    unknown = sorted(set(data) - TABLES)
    if unknown:
        raise DefinitionError(f"unknown table(s) {', '.join(f'[{k}]' for k in unknown)}")
    general = data.get("_general")
    if not isinstance(general, dict):
        raise DefinitionError("missing [_general] table")
    _reject_unknown(general, {"_name", "_namespace", "_version", "_library"}, "_general")

    api_name = general.get("_name")
    if not isinstance(api_name, str):
        raise DefinitionError("_general._name must be an identifier string")
    _identifier(api_name, "_general._name")
    namespace = general.get("_namespace")
    if not isinstance(namespace, str):
        raise DefinitionError("_general._namespace must be an identifier string")
    _identifier(namespace, "_general._namespace")
    version = general.get("_version")
    if not (
        isinstance(version, list)
        and len(version) == 4
        and all(_is_int(v) and 0 <= v <= 255 for v in version)
    ):
        raise DefinitionError("_general._version must be a list of 4 integers in 0..255")
    library = general.get("_library")
    if library is not None and not isinstance(library, str):
        raise DefinitionError("_general._library must be a string")
    if library is not None:
        check_literal_text(library, "_general._library")

    objections = _Objections(data)
    resolved_bits: dict[str, tuple[int, str]] = {}
    bit_const_groups = _each_group(
        data, "untyped_bit_const", objections,
        lambda where, body: _bit_const_group(where, body, resolved=resolved_bits),
    )
    resolved_consts: dict[str, tuple[int, str]] = {}
    const_groups = _each_group(
        data, "untyped_const", objections, lambda where, body: _const_group(where, body, resolved=resolved_consts)
    )
    string_const_groups = _each_group(data, "string_const", objections, _string_group)
    typed_consts = _each_named(data, "typed_const", objections, _typed_const)
    opaque_refs = _each_named(data, "opaque_ref", objections, _opaque_ref)
    boxed_scalars = _each_named(data, "boxed_scalar", objections, _boxed_scalar)
    struct_tables = _named_tables(data, "struct", objections)

    type_names: dict[str, str] = {}
    for category, names in (
        ("typed_const", [t.name for t in typed_consts]),
        ("opaque_ref", [o.name for o in opaque_refs]),
        ("boxed_scalar", [b.name for b in boxed_scalars]),
        ("struct", [name for name, _ in struct_tables]),
    ):
        for name in names:
            with objections.item(f"{category}.{name}"):
                if name in BUILTIN_TYPES:
                    raise DefinitionError(f"{category}.{name}: shadows builtin type {name}")
                if name in type_names:
                    raise DefinitionError(
                        f"{category}.{name}: type name already defined in {type_names[name]}"
                    )
                type_names[name] = category
    # a type whose name failed is skipped from here on, so its clash reports once
    typed_consts = tuple(t for t in typed_consts if f"typed_const.{t.name}" not in objections.failed)
    opaque_refs = tuple(o for o in opaque_refs if f"opaque_ref.{o.name}" not in objections.failed)
    boxed_scalars = tuple(b for b in boxed_scalars if f"boxed_scalar.{b.name}" not in objections.failed)

    structs: list[Struct] = []
    for name, body in struct_tables:
        where = f"struct.{name}"
        if where in objections.failed:
            continue  # its name is another type's
        with objections.item(where):
            structs.append(_struct(name, body, type_names, defined_structs={s.name for s in structs}))
        if where in objections.failed:
            del type_names[name]  # so a later use of it reports an unknown type

    enums = {t.name: t for t in typed_consts}
    functions = _each_named(
        data, "function", objections, lambda name, body: _function(name, body, type_names, enums)
    )
    functions_by_name = {f.name: f for f in functions}
    for o in opaque_refs:
        if any(f"function.{f}" in objections.failed for f in (o.ctor, o.dtor) if f is not None):
            continue  # the function it names has its own objection
        with objections.item(f"opaque_ref.{o.name}"):
            _check_lifecycle(o, functions_by_name)

    wrapped_api = None
    with objections.item("_wrapped_api"):
        wrapped_api = _wrapped_api(data.get("_wrapped_api"), {c.name for g in bit_const_groups for c in g.entries})

    api = Api(
        name=api_name,
        namespace=namespace,
        version=tuple(version),
        library=library,
        bit_const_groups=bit_const_groups,
        const_groups=const_groups,
        string_const_groups=string_const_groups,
        typed_consts=typed_consts,
        opaque_refs=opaque_refs,
        boxed_scalars=boxed_scalars,
        structs=tuple(structs),
        functions=functions,
        wrapped_api=wrapped_api,
    )
    for where, message in _identifier_clashes(api):
        objections.record(DefinitionError(message), where)
    objections.raise_any()
    return api


def _each_group(data: Mapping, key: str, objections: _Objections, parse: Callable[[str, dict], T]) -> tuple[T, ...]:
    """`parse(where, body)` for each table of the array `[[key]]`, each an item of its own."""
    bodies: list[dict] = []
    with objections.item(key):
        bodies = _group_bodies(data, key)
    parsed = []
    for i, body in enumerate(bodies):
        where = f"{key}[{i}]"
        with objections.item(where):
            parsed.append(parse(where, body))
    return tuple(parsed)


def _named_tables(data: Mapping, category: str, objections: _Objections) -> list[tuple[str, dict]]:
    """(name, body) for each `[category.<name>]` whose name and shape are sound, in document
    order; each unsound one is an objection of its own."""
    table: dict = {}
    with objections.item(category):
        table = _table(data, category)
    result = []
    for name, body in table.items():
        where = f"{category}.{name}"
        with objections.item(where):
            _identifier(name, where)
            if not isinstance(body, dict):
                raise DefinitionError(f"{where} must be a table")
            result.append((name, body))
    return result


def _each_named(
    data: Mapping, category: str, objections: _Objections, parse: Callable[[str, dict], T]
) -> tuple[T, ...]:
    """`parse(name, body)` for each `[category.<name>]`, each an item of its own."""
    parsed = []
    for name, body in _named_tables(data, category, objections):
        with objections.item(f"{category}.{name}"):
            parsed.append(parse(name, body))
    return tuple(parsed)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _identifier(name: str, where: str) -> str:
    """The language-independent rule for a name; each emitter's `validate` refuses its
    own language's keywords."""
    if name.startswith("_"):
        raise DefinitionError(f"{where}: '{name}': a key beginning with '_' is a property, not a name")
    if not _IDENTIFIER.match(name):
        raise DefinitionError(f"{where}: '{name}' is not an identifier")
    return name


def check_literal_text(value: str, where: str) -> None:
    """Refuses a string that cannot be emitted verbatim inside a C or Lua string literal:
    one holding '"', '\\' or a control character. `where` names it in the message."""
    if any(c in '"\\' or ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise DefinitionError(f"{where} must not contain '\"', '\\' or a control character")


def _table(data: Mapping, key: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise DefinitionError(f"[{key}] must be a table")
    return value


def _group_bodies(data: Mapping, key: str) -> list[dict]:
    """The tables of the array `[[key]]`."""
    groups = data.get(key, [])
    if isinstance(groups, dict):
        raise DefinitionError(f"[{key}] must be an array of tables, [[{key}]]")
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise DefinitionError(f"[[{key}]] must be an array of tables")
    return groups


def _group_properties(
    body: dict, where: str, *, properties: frozenset[str] = GROUP_PROPERTIES, floats_planned: bool = False
) -> tuple[str | None, str | None, str | None, list[tuple[str, object]]]:
    """(docstring, base type, to_string, members) of one constant group; base type and
    to_string are None where `properties` lacks them (a string constant has no fixed width
    and no conversion). `floats_planned` is `_base_type()`'s."""
    props, members = _split(body, properties, where)
    if not members:
        raise DefinitionError(f"{where}: has no entries")
    base_type = _base_type(props, where, floats_planned=floats_planned) if "_base_type" in properties else None
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    return doc, base_type, _to_string(props, where), members


def _split(body: dict, properties: frozenset[str], where: str) -> tuple[dict, list[tuple[str, object]]]:
    """A described item's `_`-prefixed properties, and its members in document order."""
    props = {k: v for k, v in body.items() if k.startswith("_")}
    _reject_unknown(props, properties, where)
    return props, [(k, v) for k, v in body.items() if not k.startswith("_")]


def _attributes(entry: object, *, naked: str, allowed: frozenset[str], where: str) -> dict:
    """An entry's attributes; a value that is not a table is sugar for `{ <naked> = value }`."""
    if not isinstance(entry, dict):
        return {naked: entry}
    plain = next((k for k in entry if not k.startswith("_")), None)
    if plain is not None:
        raise DefinitionError(f"{where}: '{plain}': entry attributes begin with _")
    _reject_unknown(entry, allowed, where)
    return entry


def _base_type(props: Mapping, where: str, *, floats_planned: bool = False) -> str:
    """`floats_planned` marks a plain constant group, where a floating-point base type is
    meaningful but not generated yet; for bit flags and enums it is a plain error."""
    value = props.get("_base_type", "i32")
    if floats_planned and value in FLOAT_TYPES:
        raise NotImplementedDefinition(f"{where}._base_type: {value} constants are not implemented")
    if not isinstance(value, str) or value not in naming.BASE_C_TYPES:
        raise DefinitionError(f"{where}._base_type must be one of {', '.join(naming.BASE_C_TYPES)}")
    return value


def _to_string(props: Mapping, where: str) -> str | None:
    """A group's `_to_string` property: absent, or a name like any other."""
    name = props.get("_to_string")
    if name is None:
        return None
    if not isinstance(name, str):
        raise DefinitionError(f"{where}._to_string must be an identifier")
    return _identifier(name, f"{where}._to_string")


def _docstring(doc: object, where: str) -> str | None:
    """`doc` validated as the docstring found at `where`."""
    if doc is None:
        return None
    if not isinstance(doc, str):
        raise DefinitionError(f"{where} must be a string")
    if "*/" in doc or "]]" in doc:
        raise DefinitionError(f"{where} must not contain '*/' or ']]'")
    if "\n" in doc or "\r" in doc:
        raise DefinitionError(f"{where} must not contain a line break")
    return doc


def _reject_unknown(body: Mapping, allowed: frozenset[str] | set[str], where: str) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise DefinitionError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _unwrap_value(entry: object, where: str) -> tuple[object, str | None, str]:
    """A constant entry as (value, docstring, format)."""
    attrs = _attributes(entry, naked="_value", allowed=CONST_ATTRIBUTES, where=where)
    fmt = attrs.get("_format", "dec")
    if fmt not in FORMATS:
        raise DefinitionError(f"{where}._format must be one of {', '.join(FORMATS)}")
    return attrs.get("_value"), _docstring(attrs.get("_docstring"), f"{where}._docstring"), fmt


def _check_fits(value: int, base_type: str, where: str) -> None:
    base = naming.BASE_C_TYPES[base_type]
    if not base.min_value <= value <= base.max_value:
        raise DefinitionError(
            f"{where}: {value} does not fit {base_type} ({base.min_value}..{base.max_value})"
        )


def _term(
    term: str, resolved: dict[str, tuple[int, str]], where: str, *, kind: str, base_type: str
) -> tuple[Term, int]:
    """A composed entry's list term and its value: a `LiteralTerm` if `term` is a literal
    (decimal or 0x-prefixed, an optional leading '-'), else the name of an earlier
    same-table entry. Either way it is of the entry's `base_type`."""
    literal = _LITERAL_TERM.match(term)
    if literal is not None:
        sign, hex_digits, dec_digits = literal.groups()
        magnitude = int(hex_digits, 16) if hex_digits is not None else int(dec_digits)
        value = -magnitude if sign else magnitude
        _check_fits(value, base_type, f"{where}: term {term}")
        return LiteralTerm(value, "hex" if hex_digits is not None else "dec"), value
    if not _IDENTIFIER.match(term):
        raise DefinitionError(
            f"{where}: term '{term}' is neither an entry name nor a literal (decimal or 0x-prefixed, "
            "an optional leading '-')"
        )
    if term not in resolved:
        raise DefinitionError(f"{where}: composes unknown constant '{term}' (only earlier {kind} entries or literals)")
    value, term_base_type = resolved[term]
    if term_base_type != base_type:
        raise DefinitionError(
            f"{where} ({base_type}) composes {kind}.{term} ({term_base_type}): a sum's terms share its _base_type"
        )
    return term, value


def _check_disjoint_bits(where: str, written: list[str], values: list[int]) -> None:
    """Refuses a bit-group sum whose terms share a bit, naming the two as written."""
    for i, (term, value) in enumerate(zip(written, values)):
        earlier = next((t for t, v in zip(written[:i], values) if v & value), None)
        if earlier is not None:
            raise DefinitionError(f"{where}: {earlier} and {term} share bits")


def _check_running_sum(where: str, written: list[str], values: list[int], base_type: str) -> None:
    """Refuses a sum whose running total, term by term in the order written, leaves
    `base_type`'s range before its last term, even where the final value fits: a constant
    expression that overflows midway is a compile error in Rust and undefined in C. The
    final value is the caller's to check."""
    total = 0
    for term, value in list(zip(written, values))[:-1]:
        total += value
        _check_fits(total, base_type, f"{where}: the running sum after term {term}")


def _bit_const_group(group_where: str, body: dict, *, resolved: dict[str, tuple[int, str]]) -> Group[BitConst]:
    """A composed value may name an entry of any earlier group of its base type or be a
    literal, so the groups share `resolved`, every entry read so far; disjoint terms sum to
    the same value as their OR, so every running total of a sum fits as its terms do."""
    group_doc, base_type, to_string, members = _group_properties(body, group_where)
    assert base_type is not None  # untyped_bit_const groups always carry _base_type
    bits = naming.BASE_C_TYPES[base_type].max_value.bit_length()  # a flag is a positive value
    consts = []
    for name, entry in members:
        where = f"untyped_bit_const.{name}"
        _identifier(name, where)
        raw, doc, fmt = _unwrap_value(entry, where)
        if _is_int(raw):
            if not 0 <= raw < bits:
                raise DefinitionError(f"{where}: bit index {raw} is outside 0..{bits - 1} for _base_type {base_type}")
            bit, parts, value = raw, (), 1 << raw
        elif isinstance(raw, list) and raw and all(isinstance(p, str) for p in raw):
            terms = [_term(p, resolved, where, kind="untyped_bit_const", base_type=base_type) for p in raw]
            _check_disjoint_bits(where, raw, [v for _, v in terms])
            bit, parts, value = None, tuple(t for t, _ in terms), sum(v for _, v in terms)
        else:
            raise DefinitionError(
                f"{where}: must be a bit index or a non-empty list of constant names or literals"
            )
        consts.append(BitConst(name=name, docstring=doc, bit=bit, parts=parts, value=value, format=fmt))
        resolved[name] = value, base_type
    return Group(name=group_where, docstring=group_doc, base_type=base_type, to_string=to_string, entries=tuple(consts))


def _int_entry(name: str, entry: object, where: str, *, base_type: str) -> EnumEntry:
    _identifier(name, where)
    value, doc, fmt = _unwrap_value(entry, where)
    if not _is_int(value):
        raise DefinitionError(f"{where}: value must be an integer")
    _check_fits(value, base_type, where)
    return EnumEntry(name=name, docstring=doc, value=value, format=fmt)


def _plain_const_entry(
    name: str, entry: object, where: str, *, base_type: str, resolved: dict[str, tuple[int, str]]
) -> EnumEntry:
    """An untyped_const entry: a plain integer, or a list summing earlier untyped_const
    entries and literals, the same composition untyped_bit_const uses (without the
    disjointness rule, since a plain group is arithmetic, not bit flags)."""
    _identifier(name, where)
    raw, doc, fmt = _unwrap_value(entry, where)
    if isinstance(raw, float):
        raise NotImplementedDefinition(f"{where}: f64 constants are not implemented")
    if _is_int(raw):
        value, parts = raw, ()
    elif isinstance(raw, list) and raw and all(isinstance(p, str) for p in raw):
        terms = [_term(p, resolved, where, kind="untyped_const", base_type=base_type) for p in raw]
        _check_running_sum(where, raw, [v for _, v in terms], base_type)
        parts, value = tuple(t for t, _ in terms), sum(v for _, v in terms)
    else:
        raise DefinitionError(f"{where}: must be an integer or a non-empty list of constant names or literals")
    _check_fits(value, base_type, where)
    resolved[name] = value, base_type
    return EnumEntry(name=name, docstring=doc, value=value, format=fmt, parts=parts)


def _const_group(group_where: str, body: dict, *, resolved: dict[str, tuple[int, str]]) -> Group[EnumEntry]:
    """A composed value may name an entry of any earlier group of its base type, so the
    groups share `resolved`, every entry read so far."""
    doc, base_type, to_string, members = _group_properties(body, group_where, floats_planned=True)
    assert base_type is not None  # untyped_const groups always carry _base_type
    entries = tuple(
        _plain_const_entry(name, entry, f"untyped_const.{name}", base_type=base_type, resolved=resolved)
        for name, entry in members
    )
    return Group(name=group_where, docstring=doc, base_type=base_type, to_string=to_string, entries=entries)


def _string_group(where: str, body: dict) -> Group[StringConst]:
    doc, _, _, members = _group_properties(body, where, properties=STRING_GROUP_PROPERTIES)
    return Group(
        name=where, docstring=doc, base_type=None, to_string=None,
        entries=tuple(_string_const(name, entry) for name, entry in members),
    )


def _string_const(name: str, entry: object) -> StringConst:
    where = f"string_const.{name}"
    _identifier(name, where)
    attrs = _attributes(entry, naked="_value", allowed=frozenset({"_value", "_docstring"}), where=where)
    value = attrs.get("_value")
    if not isinstance(value, str):
        raise DefinitionError(f"{where}: value must be a string")
    check_literal_text(value, f"{where}: value")
    return StringConst(name=name, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"), value=value)


def _typed_const(name: str, body: dict) -> TypedConst:
    where = f"typed_const.{name}"
    props, members = _split(body, GROUP_PROPERTIES, where)
    base_type = _base_type(props, where)
    entries = [_int_entry(key, entry, f"{where}.{key}", base_type=base_type) for key, entry in members]
    if not entries:
        raise DefinitionError(f"{where}: has no entries")
    by_value: dict[int, str] = {}
    for e in entries:
        if e.value in by_value:
            raise DefinitionError(f"{where}.{e.name}: value {e.value} already given to {where}.{by_value[e.value]}")
        by_value[e.value] = e.name
    return TypedConst(
        name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        entries=tuple(entries), base_type=base_type, to_string=_to_string(props, where),
    )


def _opaque_ref(name: str, body: dict) -> OpaqueRef:
    where = f"opaque_ref.{name}"
    props, members = _split(body, OPAQUE_PROPERTIES, where)
    if members:
        raise DefinitionError(f"{where}: '{members[0][0]}': an opaque_ref has no members; its properties begin with _")
    for key in ("_ctor", "_dtor"):
        if not isinstance(props.get(key, ""), str):
            raise DefinitionError(f"{where}.{key} must be a function name")
    class_name = props.get("_class", name)
    if "_class" in props:
        if not isinstance(class_name, str):
            raise DefinitionError(f"{where}._class must be an identifier")
        _identifier(class_name, f"{where}._class")
        if not _LOWERCASE_IDENTIFIER.match(class_name):
            raise DefinitionError(f"{where}._class: '{class_name}' must be lowercase; each binding applies its own casing")
    return OpaqueRef(
        name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        ctor=props.get("_ctor"), dtor=props.get("_dtor"), class_name=class_name,
    )


def _boxed_scalar(name: str, body: dict) -> BoxedScalar:
    where = f"boxed_scalar.{name}"
    props, members = _split(body, BOXED_PROPERTIES, where)
    if members:
        raise DefinitionError(f"{where}: '{members[0][0]}': a boxed_scalar has no members; its properties begin with _")
    base_type = props.get("_base_type")
    if base_type not in INTEGER_TYPES:
        raise DefinitionError(f"{where}._base_type is required, one of {', '.join(INTEGER_TYPES)}")
    return BoxedScalar(name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"), base_type=base_type)


def _check_lifecycle(o: OpaqueRef, functions: Mapping[str, Function]) -> None:
    where = f"opaque_ref.{o.name}"
    if o.dtor is not None and o.ctor is None:
        raise DefinitionError(f"{where}._dtor: requires _ctor")
    if o.ctor is None:
        return
    ctor = functions.get(o.ctor)
    if ctor is None or sum(p.type == o.name and p.ref == "out" for p in ctor.params) != 1:
        raise DefinitionError(
            f"{where}._ctor: '{o.ctor}' must name a function with exactly one {o.name} parameter of _ref \"out\""
        )
    memory = next((p for p in ctor.params if p.ref == "out" and p.type == "memory"), None)
    if memory is not None:
        raise DefinitionError(
            f"{where}._ctor: function.{ctor.name}.{memory.name}: a constructor cannot cache a memory out parameter"
        )
    inout = next((p for p in ctor.params if p.ref == "inout"), None)
    if inout is not None:
        raise DefinitionError(
            f"{where}._ctor: function.{ctor.name}.{inout.name}: a constructor has no inout parameter"
        )
    if o.dtor is not None:
        dtor = functions.get(o.dtor)
        if dtor is None or [(p.type, p.ref) for p in dtor.params] != [(o.name, None)]:
            raise DefinitionError(
                f"{where}._dtor: '{o.dtor}' must name a function whose only parameter is a {o.name} by value"
            )


def _variable(
    entry: object, *, allowed: frozenset[str], type_names: dict[str, str], where: str
) -> tuple[str, dict]:
    """A field or parameter as (type, attributes), its type checked to exist."""
    attrs = _attributes(entry, naked="_type", allowed=allowed, where=where)
    type_name = attrs.get("_type")
    if not isinstance(type_name, str):
        raise DefinitionError(f"{where}: must be a type name or a table with _type")
    if type_name not in BUILTIN_TYPES and type_name not in type_names:
        raise DefinitionError(f"{where}: unknown type '{type_name}'")
    return type_name, attrs


def _struct(name: str, body: dict, type_names: dict[str, str], *, defined_structs: set[str]) -> Struct:
    """A struct whose fields are checked each on its own, every field's objection reported."""
    where = f"struct.{name}"
    props, members = _split(body, frozenset({"_docstring"}), where)
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    if not members:
        raise DefinitionError(f"{where}: has no fields")
    objections = _Objections()
    fields = []
    for key, entry in members:
        with objections.item(f"{where}.{key}"):
            fields.append(_field(key, entry, f"{where}.{key}", type_names=type_names, defined_structs=defined_structs))
    objections.raise_any()
    return Struct(name=name, docstring=doc, fields=tuple(fields))


def _field(key: str, entry: object, where: str, *, type_names: dict[str, str], defined_structs: set[str]) -> Field:
    _identifier(key, where)
    type_name, attrs = _variable(entry, allowed=FIELD_ATTRIBUTES, type_names=type_names, where=where)
    if type_name == "memory":
        raise DefinitionError(f"{where}: 'memory' is not a field type")
    if type_names.get(type_name) == "struct" and type_name not in defined_structs:
        raise DefinitionError(f"{where}: struct '{type_name}' must be defined before it is used")
    return Field(name=key, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"), type=type_name)


def _function(
    name: str, body: dict, type_names: dict[str, str], enums: Mapping[str, TypedConst]
) -> Function:
    """A function whose `_return` and parameters are checked each on its own, every one's
    objection reported."""
    where = f"function.{name}"
    props, members = _split(body, frozenset({"_docstring", "_return"}), where)
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    objections = _Objections()
    returns = ""
    with objections.item(f"{where}._return"):
        returns = _return(props.get("_return"), where, enums)
    names = {key for key, _ in members}
    params = []
    for key, entry in members:
        with objections.item(f"{where}.{key}"):
            params.append(_param(key, entry, f"{where}.{key}", type_names=type_names, names=names))
    objections.raise_any()
    return Function(name=name, docstring=doc, returns=returns, params=tuple(params))


def _return(returns: object, where: str, enums: Mapping[str, TypedConst]) -> str:
    """The `_return` of the function at `where`."""
    if not isinstance(returns, str):
        raise DefinitionError(f"{where}: missing '_return' naming a typed_const")
    if returns not in enums:
        raise DefinitionError(f"{where}._return: unknown typed_const '{returns}'")
    if not any(e.value == 0 for e in enums[returns].entries):
        raise DefinitionError(f"{where}._return: typed_const '{returns}' has no zero-valued entry for success")
    return returns


def _param(key: str, entry: object, where: str, *, type_names: dict[str, str], names: set[str]) -> Param:
    """A parameter of a function whose parameters are `names`."""
    _identifier(key, where)
    type_name, attrs = _variable(entry, allowed=PARAM_ATTRIBUTES, type_names=type_names, where=where)
    ref = attrs.get("_ref")
    if ref is not None and ref not in REFS:
        raise DefinitionError(f"{where}._ref must be one of {', '.join(REFS)}")
    if type_name == "memory" and ref is None:
        raise DefinitionError(f"{where}: a 'memory' parameter needs _ref")
    count_type = attrs.get("_count")
    if type_name == "memory" and count_type not in COUNT_TYPES:
        raise DefinitionError(f"{where}: a 'memory' parameter requires _count, one of {', '.join(COUNT_TYPES)}")
    if type_name != "memory" and count_type is not None:
        raise DefinitionError(f"{where}._count: only a 'memory' parameter has a count")
    if count_type is not None and naming.count_param(key) in names:
        raise DefinitionError(f"{where}: its count parameter {naming.count_param(key)} is already a parameter")
    optional = attrs.get("_optional", False)
    if not isinstance(optional, bool):
        raise DefinitionError(f"{where}._optional must be true or false")
    if optional and ref is None:
        raise DefinitionError(f"{where}._optional: a by-value parameter has no null to pass")
    if optional and type_name == "memory" and ref != "in":
        raise DefinitionError(f"{where}._optional: a memory parameter is optional only with _ref = \"in\"")
    return Param(
        name=key, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"),
        type=type_name, ref=ref, count_type=count_type, optional=optional,
    )


def _wrapped_api(body: object, bit_names: set[str]) -> WrappedApi | None:
    if body is None:
        return None
    if not isinstance(body, dict):
        raise DefinitionError("[_wrapped_api] must be a table")
    props, members = _split(body, frozenset({"_header"}), "_wrapped_api")
    header = props.get("_header")
    if not isinstance(header, str):
        raise DefinitionError("_wrapped_api._header must be a string")
    check_literal_text(header, "_wrapped_api._header")
    if header.startswith(("/", "../")):
        raise DefinitionError(
            "_wrapped_api._header must be relative to the project directory, not absolute or beginning with '../'"
        )
    pins = []
    for key, macro in members:
        where = f"_wrapped_api.{key}"
        if key not in bit_names:
            raise DefinitionError(f"{where}: pins undefined untyped_bit_const '{key}'")
        if not isinstance(macro, str) or not _IDENTIFIER.match(macro):
            raise DefinitionError(f"{where}: must be a macro name")
        pins.append((key, macro))
    return WrappedApi(header, tuple(pins))


def _identifier_clashes(api: Api) -> list[tuple[str, str]]:
    """(where, objection) for every generated C identifier, constant or declaration, that a
    later item defines again, naming the first definer."""
    ns = api.namespace
    idents = [(where, naming.const_name(ns, name)) for where, name in api.constant_names(version=True)]
    idents += [(f"typed_const.{t.name}", naming.type_name(ns, t.name)) for t in api.typed_consts]
    for o in api.opaque_refs:
        where = f"opaque_ref.{o.name}"
        idents += [(where, naming.type_name(ns, o.name)), (where, naming.opaque_struct(ns, o.name))]
    idents += [(f"boxed_scalar.{b.name}", naming.type_name(ns, b.name)) for b in api.boxed_scalars]
    idents += [(f"struct.{s.name}", naming.type_name(ns, s.name)) for s in api.structs]
    idents += [(f"function.{f.name}", naming.function_name(ns, f.name)) for f in api.functions]
    clashes = []
    for ident, (first, *later) in duplicates(idents).items():
        clashes += [(where, f"{where}: C identifier {ident} already defined by {first}") for where in later]
    return clashes
