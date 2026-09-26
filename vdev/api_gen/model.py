"""Load, validate and normalise an .adef.toml API definition.

Parameter and field order is document order. The loader relies on `tomllib`
building insertion-ordered dicts, so iterating a table yields its keys in the
order they appear in the file.
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from api_gen import naming

BUILTIN_TYPES = frozenset({*naming.BUILTIN_C_TYPES, "memory"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_LOWERCASE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")
# A composed entry's literal term: decimal or 0x-prefixed hex, an optional leading '-'.
_LITERAL_TERM = re.compile(r"(-?)(?:0x([0-9a-fA-F]+)|([0-9]+))\Z")
FORMATS = ("dec", "hex")
REFS = ("in", "out", "inout")
TABLES = frozenset(
    {"_general", "untyped_bit_const", "untyped_const", "string_const", "typed_const", "opaque_ref", "struct", "function",
     "_driver_data"}
)
GROUP_PROPERTIES = frozenset({"_docstring", "_base_type", "_to_string"})
STRING_GROUP_PROPERTIES = frozenset({"_docstring"})  # a string constant has no fixed-width representation
OPAQUE_PROPERTIES = frozenset({"_docstring", "_class", "_ctor", "_dtor"})
CONST_ATTRIBUTES = frozenset({"_value", "_docstring", "_format"})
FIELD_ATTRIBUTES = frozenset({"_type", "_docstring"})
PARAM_ATTRIBUTES = frozenset({"_type", "_ref", "_count", "_optional", "_docstring"})
COUNT_TYPES = ("u8", "u16", "u32", "u64")
FLOAT_TYPES = ("f32", "f64")


class DefinitionError(Exception):
    """The definition cannot be turned into an API."""


class NotImplementedDefinition(DefinitionError):
    """The definition says something the format allows and the generator cannot produce yet."""


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
    bit: int | None  # set for a single bit
    parts: tuple[Term, ...]  # set for a sum, in the order written
    value: int  # the resolved value: 1 << bit, or the (overlap-checked) sum of parts
    format: str  # one of FORMATS: how a literal of the value is spelled


@dataclass(frozen=True, kw_only=True)
class EnumEntry(Node):
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
class Field(Node):
    type: str


@dataclass(frozen=True, kw_only=True)
class Struct(Node):
    fields: tuple[Field, ...]


@dataclass(frozen=True, kw_only=True)
class Param(Node):
    type: str
    ref: str | None  # one of REFS; None is by value
    count_type: str | None  # memory only, one of COUNT_TYPES: the type of its naming.count_param
    optional: bool  # only with a ref, and on memory only with ref "in"


@dataclass(frozen=True, kw_only=True)
class Function(Node):
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


@dataclass(frozen=True)
class DriverData:
    header: str  # relative to the exercises directory
    const_pins: tuple[tuple[str, str], ...]  # (untyped_bit_const name, driver macro)


@dataclass(frozen=True)
class Api:
    namespace: str
    version: tuple[int, int, int, int]
    library: str | None
    bit_const_groups: tuple[Group[BitConst], ...]
    const_groups: tuple[Group[EnumEntry], ...]
    string_const_groups: tuple[Group[StringConst], ...]
    typed_consts: tuple[TypedConst, ...]
    opaque_refs: tuple[OpaqueRef, ...]
    structs: tuple[Struct, ...]
    functions: tuple[Function, ...]
    driver_data: DriverData | None

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

    def constant_names(self, *, enum_entries: bool = True) -> list[tuple[str, str]]:
        """(where, name) for every constant of every kind in document order, typed enum
        entries last unless `enum_entries` is false: everything that becomes a
        `naming.const_name`."""
        names = [(f"untyped_bit_const.{c.name}", c.name) for c in self.bit_consts]
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
        """One of "builtin", "enum", "opaque", "struct" for a validated type name."""
        if type_name in BUILTIN_TYPES:
            return "builtin"
        if any(t.name == type_name for t in self.typed_consts):
            return "enum"
        if any(o.name == type_name for o in self.opaque_refs):
            return "opaque"
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
    """Each name that `pairs`, (name, what defines it), holds more than once, with every
    definer in order, in the order the names are first seen."""
    definers: dict[str, list[str]] = {}
    for name, definer in pairs:
        definers.setdefault(name, []).append(definer)
    return {name: found for name, found in definers.items() if len(found) > 1}


def load(path: Path) -> Api:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise DefinitionError(str(e)) from e
    return from_dict(data)


def from_dict(data: Mapping) -> Api:
    unknown = sorted(set(data) - TABLES)
    if unknown:
        raise DefinitionError(f"unknown table(s) {', '.join(f'[{k}]' for k in unknown)}")
    general = data.get("_general")
    if not isinstance(general, dict):
        raise DefinitionError("missing [_general] table")
    _reject_unknown(general, {"_namespace", "_version", "_library"}, "_general")

    namespace = general.get("_namespace")
    if not isinstance(namespace, str) or not _IDENTIFIER.match(namespace):
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

    bit_const_groups = _bit_const_groups(_groups(data, "untyped_bit_const"))
    const_groups = _const_groups(_groups(data, "untyped_const"))
    string_const_groups = tuple(
        Group(
            name=where, docstring=doc, base_type=None, to_string=None,
            entries=tuple(_string_const(name, entry) for name, entry in members),
        )
        for where, doc, _, _, members in _groups(data, "string_const", properties=STRING_GROUP_PROPERTIES)
    )
    typed_consts = tuple(
        _typed_const(name, body)
        for name, body in _named_tables(_table(data, "typed_const"), "typed_const")
    )
    opaque_refs = [
        _opaque_ref(name, body) for name, body in _named_tables(_table(data, "opaque_ref"), "opaque_ref")
    ]
    struct_tables = _named_tables(_table(data, "struct"), "struct")

    type_names: dict[str, str] = {}
    for category, names in (
        ("typed_const", [t.name for t in typed_consts]),
        ("opaque_ref", [o.name for o in opaque_refs]),
        ("struct", [name for name, _ in struct_tables]),
    ):
        for name in names:
            if name in BUILTIN_TYPES:
                raise DefinitionError(f"{category}.{name}: shadows builtin type {name}")
            if name in type_names:
                raise DefinitionError(
                    f"{category}.{name}: type name already defined in {type_names[name]}"
                )
            type_names[name] = category

    structs: list[Struct] = []
    for name, body in struct_tables:
        structs.append(_struct(name, body, type_names, defined_structs={s.name for s in structs}))

    enums = {t.name: t for t in typed_consts}
    functions = tuple(
        _function(name, body, type_names, enums)
        for name, body in _named_tables(_table(data, "function"), "function")
    )
    _check_lifecycles(opaque_refs, {f.name: f for f in functions})

    api = Api(
        namespace=namespace,
        version=tuple(version),
        library=library,
        bit_const_groups=bit_const_groups,
        const_groups=const_groups,
        string_const_groups=string_const_groups,
        typed_consts=typed_consts,
        opaque_refs=tuple(opaque_refs),
        structs=tuple(structs),
        functions=functions,
        driver_data=_driver_data(data.get("_driver_data"), {c.name for g in bit_const_groups for c in g.entries}),
    )
    _check_unique_identifiers(api)
    return api


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


def _groups(
    data: Mapping, key: str, *, properties: frozenset[str] = GROUP_PROPERTIES
) -> list[tuple[str, str | None, str | None, str | None, list[tuple[str, object]]]]:
    """(where, docstring, base type, to_string, members) for each table of the array `[[key]]`;
    base type and to_string are None where `properties` lacks them (a string constant has no
    fixed width and no conversion)."""
    groups = data.get(key, [])
    if isinstance(groups, dict):
        raise DefinitionError(f"[{key}] must be an array of tables, [[{key}]]")
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise DefinitionError(f"[[{key}]] must be an array of tables")
    result = []
    for i, body in enumerate(groups):
        where = f"{key}[{i}]"
        props, members = _split(body, properties, where)
        if not members:
            raise DefinitionError(f"{where}: has no entries")
        base_type = (
            _base_type(props, where, floats_planned=key == "untyped_const") if "_base_type" in properties else None
        )
        doc = _docstring(props.get("_docstring"), f"{where}._docstring")
        result.append((where, doc, base_type, _to_string(props, where), members))
    return result


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


def _named_tables(table: dict, category: str) -> list[tuple[str, dict]]:
    result = []
    for name, body in table.items():
        where = f"{category}.{name}"
        _identifier(name, where)
        if not isinstance(body, dict):
            raise DefinitionError(f"{where} must be a table")
        result.append((name, body))
    return result


def _docstring(doc: object, where: str) -> str | None:
    """`doc` validated as the docstring found at `where`."""
    if doc is None:
        return None
    if not isinstance(doc, str):
        raise DefinitionError(f"{where} must be a string")
    if "*/" in doc or "]]" in doc:
        raise DefinitionError(f"{where} must not contain '*/' or ']]'")
    return doc


def _reject_unknown(body: Mapping, allowed: set[str], where: str) -> None:
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


def _bit_const_groups(
    groups: list[tuple[str, str | None, str | None, str | None, list[tuple[str, object]]]]
) -> tuple[Group[BitConst], ...]:
    """A composed value may name an entry of any earlier group of its base type or be a
    literal, so the groups are read as one sequence; disjoint terms sum to the same value
    as their OR."""
    resolved: dict[str, tuple[int, str]] = {}
    result = []
    for group_where, group_doc, base_type, to_string, members in groups:
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
        result.append(
            Group(name=group_where, docstring=group_doc, base_type=base_type, to_string=to_string, entries=tuple(consts))
        )
    return tuple(result)


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
        parts, value = tuple(t for t, _ in terms), sum(v for _, v in terms)
    else:
        raise DefinitionError(f"{where}: must be an integer or a non-empty list of constant names or literals")
    _check_fits(value, base_type, where)
    resolved[name] = value, base_type
    return EnumEntry(name=name, docstring=doc, value=value, format=fmt, parts=parts)


def _const_groups(
    groups: list[tuple[str, str | None, str | None, str | None, list[tuple[str, object]]]]
) -> tuple[Group[EnumEntry], ...]:
    """A composed value may name an entry of any earlier group of its base type, so the
    groups are read as one sequence."""
    resolved: dict[str, tuple[int, str]] = {}
    result = []
    for group_where, doc, base_type, to_string, members in groups:
        assert base_type is not None  # untyped_const groups always carry _base_type
        entries = tuple(
            _plain_const_entry(name, entry, f"untyped_const.{name}", base_type=base_type, resolved=resolved)
            for name, entry in members
        )
        result.append(Group(name=group_where, docstring=doc, base_type=base_type, to_string=to_string, entries=entries))
    return tuple(result)


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
        if not isinstance(class_name, str) or not _IDENTIFIER.match(class_name):
            raise DefinitionError(f"{where}._class must be an identifier")
        _identifier(class_name, f"{where}._class")
        if not _LOWERCASE_IDENTIFIER.match(class_name):
            raise DefinitionError(f"{where}._class: '{class_name}' must be lowercase; each binding applies its own casing")
    return OpaqueRef(
        name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        ctor=props.get("_ctor"), dtor=props.get("_dtor"), class_name=class_name,
    )


def _check_lifecycles(opaque_refs: list[OpaqueRef], functions: Mapping[str, Function]) -> None:
    for o in opaque_refs:
        where = f"opaque_ref.{o.name}"
        if o.dtor is not None and o.ctor is None:
            raise DefinitionError(f"{where}._dtor: requires _ctor")
        if o.ctor is None:
            continue
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
    props, members = _split(body, frozenset({"_docstring"}), f"struct.{name}")
    fields = []
    for key, entry in members:
        where = f"struct.{name}.{key}"
        _identifier(key, where)
        type_name, attrs = _variable(entry, allowed=FIELD_ATTRIBUTES, type_names=type_names, where=where)
        if type_name == "memory":
            raise DefinitionError(f"{where}: 'memory' is not a field type")
        if type_names.get(type_name) == "struct" and type_name not in defined_structs:
            raise DefinitionError(f"{where}: struct '{type_name}' must be defined before it is used")
        fields.append(Field(name=key, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"), type=type_name))
    if not fields:
        raise DefinitionError(f"struct.{name}: has no fields")
    return Struct(name=name, docstring=_docstring(props.get("_docstring"), f"struct.{name}._docstring"), fields=tuple(fields))


def _function(
    name: str, body: dict, type_names: dict[str, str], enums: Mapping[str, TypedConst]
) -> Function:
    where = f"function.{name}"
    props, members = _split(body, frozenset({"_docstring", "_return"}), where)
    returns = props.get("_return")
    if not isinstance(returns, str):
        raise DefinitionError(f"{where}: missing '_return' naming a typed_const")
    if returns not in enums:
        raise DefinitionError(f"{where}._return: unknown typed_const '{returns}'")
    if not any(e.value == 0 for e in enums[returns].entries):
        raise DefinitionError(f"{where}._return: typed_const '{returns}' has no zero-valued entry for success")
    params = []
    for key, entry in members:
        pwhere = f"{where}.{key}"
        _identifier(key, pwhere)
        type_name, attrs = _variable(entry, allowed=PARAM_ATTRIBUTES, type_names=type_names, where=pwhere)
        ref = attrs.get("_ref")
        if ref is not None and ref not in REFS:
            raise DefinitionError(f"{pwhere}._ref must be one of {', '.join(REFS)}")
        if type_name == "memory" and ref is None:
            raise DefinitionError(f"{pwhere}: a 'memory' parameter needs _ref")
        count_type = attrs.get("_count")
        if type_name == "memory" and count_type not in COUNT_TYPES:
            raise DefinitionError(f"{pwhere}: a 'memory' parameter requires _count, one of {', '.join(COUNT_TYPES)}")
        if type_name != "memory" and count_type is not None:
            raise DefinitionError(f"{pwhere}._count: only a 'memory' parameter has a count")
        optional = attrs.get("_optional", False)
        if not isinstance(optional, bool):
            raise DefinitionError(f"{pwhere}._optional must be true or false")
        if optional and ref is None:
            raise DefinitionError(f"{pwhere}._optional: a by-value parameter has no null to pass")
        if optional and type_name == "memory" and ref != "in":
            raise DefinitionError(f"{pwhere}._optional: a memory parameter is optional only with _ref = \"in\"")
        params.append(
            Param(
                name=key, docstring=_docstring(attrs.get("_docstring"), f"{pwhere}._docstring"),
                type=type_name, ref=ref, count_type=count_type, optional=optional,
            )
        )
    names = {p.name for p in params}
    for p in params:
        if p.count_type is not None and naming.count_param(p.name) in names:
            raise DefinitionError(
                f"{where}.{p.name}: its count parameter {naming.count_param(p.name)} is already a parameter"
            )
    return Function(
        name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        returns=returns, params=tuple(params),
    )


def _driver_data(body: object, bit_names: set[str]) -> DriverData | None:
    if body is None:
        return None
    if not isinstance(body, dict):
        raise DefinitionError("[_driver_data] must be a table")
    _reject_unknown(body, {"_header", "const_pins"}, "_driver_data")
    header = body.get("_header")
    if not isinstance(header, str):
        raise DefinitionError("_driver_data._header must be a string")
    check_literal_text(header, "_driver_data._header")
    pins_table = body.get("const_pins", {})
    if not isinstance(pins_table, dict):
        raise DefinitionError("_driver_data.const_pins must be a table")
    pins = []
    for key, macro in pins_table.items():
        where = f"_driver_data.const_pins.{key}"
        if key not in bit_names:
            raise DefinitionError(f"{where}: pins undefined untyped_bit_const '{key}'")
        if not isinstance(macro, str) or not _IDENTIFIER.match(macro):
            raise DefinitionError(f"{where}: must be a driver macro name")
        pins.append((key, macro))
    return DriverData(header, tuple(pins))


def _check_unique_identifiers(api: Api) -> None:
    """Every generated C identifier, constants and declarations alike, is defined once."""
    ns = api.namespace
    idents = [(naming.version_const(ns), "the API version constant")]
    idents += [(naming.const_name(ns, name), where) for where, name in api.constant_names()]
    idents += [(naming.type_name(ns, t.name), f"typed_const.{t.name}") for t in api.typed_consts]
    for o in api.opaque_refs:
        where = f"opaque_ref.{o.name}"
        idents += [(naming.type_name(ns, o.name), where), (naming.opaque_struct(ns, o.name), where)]
    idents += [(naming.type_name(ns, s.name), f"struct.{s.name}") for s in api.structs]
    idents += [(naming.function_name(ns, f.name), f"function.{f.name}") for f in api.functions]
    repeated = duplicates(idents)
    if repeated:
        ident, (first, second, *_) = next(iter(repeated.items()))
        raise DefinitionError(f"{second}: C identifier {ident} already defined by {first}")
