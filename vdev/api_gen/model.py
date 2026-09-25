"""Load, validate and normalise an .adef.toml API definition.

Parameter and field order is document order. The loader relies on `tomllib`
building insertion-ordered dicts, so iterating a table yields its keys in the
order they appear in the file.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from api_gen import naming

RESERVED_NAMES = frozenset(
    (
        # C
        "auto break case char const continue default do double else enum extern float for goto if "
        "inline int long register restrict return short signed sizeof static struct switch typedef "
        "union unsigned void volatile while "
        # C++
        "alignas alignof and_eq asm bitand bitor bool catch char8_t char16_t char32_t class compl "
        "concept consteval constexpr constinit const_cast co_await co_return co_yield decltype "
        "delete dynamic_cast explicit export false friend mutable namespace new noexcept not not_eq "
        "nullptr operator or_eq private protected public reinterpret_cast requires static_assert "
        "static_cast template this thread_local throw true try typeid typename using virtual "
        "wchar_t xor xor_eq "
        # Lua
        "and break do else elseif end false for function goto if in local nil not or repeat return "
        "then true until while"
    ).split()
)
# Names the generated Lua binds as locals beside a function's parameters. Other names
# never share a scope with them, so an enum may be called `result`.
GENERATED_LOCALS = frozenset({"self", "result", "lib", "M", "ffi", "indent"})
BUILTIN_TYPES = frozenset({"u32", "u64", "memory"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
FORMATS = ("dec", "hex")
REFS = ("in", "out", "inout")
TABLES = frozenset(
    {"_general", "untyped_bit_const", "untyped_const", "string_const", "typed_const", "opaque_ref", "struct", "function",
     "_driver_data"}
)
GROUP_PROPERTIES = frozenset({"_docstring", "_base_type"})
OPAQUE_PROPERTIES = frozenset({"_docstring", "_class", "_ctor", "_dtor"})
CONST_ATTRIBUTES = frozenset({"_value", "_docstring", "_format"})
FIELD_ATTRIBUTES = frozenset({"_type", "_docstring"})
PARAM_ATTRIBUTES = frozenset({"_type", "_ref", "_count", "_optional", "_docstring"})
COUNT_TYPES = ("u32", "u64")


class DefinitionError(Exception):
    """The definition cannot be turned into an API."""


@dataclass(frozen=True)
class BitConst:
    key: str
    bit: int | None  # set for a single bit
    parts: tuple[str, ...]  # set for a mask composed of earlier entries
    docstring: str | None
    format: str  # one of FORMATS: how a literal of the value is spelled


@dataclass(frozen=True)
class EnumEntry:
    key: str
    value: int
    docstring: str | None
    format: str  # one of FORMATS


@dataclass(frozen=True)
class BitConstGroup:
    docstring: str | None
    base_type: str  # a key of naming.BASE_C_TYPES
    entries: tuple[BitConst, ...]


@dataclass(frozen=True)
class ConstGroup:
    docstring: str | None
    base_type: str  # a key of naming.BASE_C_TYPES
    entries: tuple[EnumEntry, ...]  # an enum entry's shape, without the enum


@dataclass(frozen=True)
class StringConst:
    key: str
    value: str  # holds no '"', '\' or newline, so it is a valid C and Lua literal as-is
    docstring: str | None


@dataclass(frozen=True)
class TypedConst:
    name: str
    entries: tuple[EnumEntry, ...]
    docstring: str | None
    base_type: str  # a key of naming.BASE_C_TYPES


@dataclass(frozen=True)
class OpaqueRef:
    name: str
    docstring: str | None
    ctor: str | None  # function with exactly one out parameter of this type
    dtor: str | None  # function taking only this type by value; set only with ctor
    class_name: str  # an identifier as the definition writes it; each binding applies its own idiom


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    docstring: str | None


@dataclass(frozen=True)
class Struct:
    name: str
    fields: tuple[Field, ...]
    docstring: str | None


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    ref: str | None  # one of REFS; None is by value
    count_type: str | None  # memory only, one of COUNT_TYPES: the type of its naming.count_param
    optional: bool
    docstring: str | None


@dataclass(frozen=True)
class Function:
    name: str
    returns: str
    params: tuple[Param, ...]
    docstring: str | None

    def docs(self) -> list[str]:
        """The function's docstring, if any, followed by each parameter's as `name: text`."""
        docs = [self.docstring] if self.docstring else []
        docs += [f"{p.name}: {p.docstring}" for p in self.params if p.docstring]
        return docs


@dataclass(frozen=True)
class DriverData:
    header: str  # relative to the exercises directory
    const_pins: tuple[tuple[str, str], ...]  # (untyped_bit_const key, driver macro)


@dataclass(frozen=True)
class Api:
    namespace: str
    version: tuple[int, int, int, int]
    library: str | None
    bit_const_groups: tuple[BitConstGroup, ...]
    const_groups: tuple[ConstGroup, ...]
    string_consts: tuple[StringConst, ...]
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

    def version_value(self) -> int:
        """The version packed into one 32-bit value, most-significant byte first."""
        shifts = (24, 16, 8, 0)
        return sum(b << s for b, s in zip(self.version, shifts))


def load(path: Path) -> Api:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DefinitionError(str(e)) from e
    return from_dict(data)


def from_dict(data: Mapping) -> Api:
    unknown = sorted(set(data) - TABLES)
    if unknown:
        raise DefinitionError(f"unknown table(s) {', '.join(f'[{k}]' for k in unknown)}")
    general = data.get("_general")
    if not isinstance(general, dict):
        raise DefinitionError("missing [_general] table")
    if "name" in general:
        raise DefinitionError("_general: unknown key name (the definition's file name is the output stem)")
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
    if version[0] > 127:
        raise DefinitionError("_general._version: first byte must be 0..127 (enumerators must fit int)")
    library = general.get("_library")
    if library is not None and not isinstance(library, str):
        raise DefinitionError("_general._library must be a string")
    if library is not None:
        _quote_free(library, "_general._library")

    bit_const_groups = _bit_const_groups(_groups(data, "untyped_bit_const"))
    const_groups = tuple(
        ConstGroup(
            doc,
            base_type,
            tuple(_int_entry(key, entry, f"untyped_const.{key}", base_type=base_type) for key, entry in members),
        )
        for doc, base_type, members in _groups(data, "untyped_const")
    )
    string_consts = tuple(
        _string_const(key, entry) for key, entry in _table(data, "string_const").items()
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
        string_consts=string_consts,
        typed_consts=typed_consts,
        opaque_refs=tuple(opaque_refs),
        structs=tuple(structs),
        functions=functions,
        driver_data=_driver_data(data.get("_driver_data"), {c.key for g in bit_const_groups for c in g.entries}),
    )
    _check_unique_identifiers(api)
    return api


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _identifier(name: str, where: str, *, reserved: frozenset[str] = RESERVED_NAMES) -> str:
    if name.startswith("_"):
        raise DefinitionError(f"{where}: '{name}': a key beginning with '_' is a property, not a name")
    if not _IDENTIFIER.match(name):
        raise DefinitionError(f"{where}: '{name}' is not an identifier")
    if name in reserved:
        raise DefinitionError(f"{where}: '{name}' is a C, C++ or Lua keyword or a name the generated code binds")
    return name


def _quote_free(value: str, where: str) -> None:
    """For a string emitted inside a C or Lua string literal."""
    if '"' in value or "\\" in value:
        raise DefinitionError(f"{where} must not contain '\"' or '\\'")


def _table(data: Mapping, key: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise DefinitionError(f"[{key}] must be a table")
    return value


def _groups(data: Mapping, key: str) -> list[tuple[str | None, str, list[tuple[str, object]]]]:
    """(docstring, base type, members) for each table of the array `[[key]]`."""
    groups = data.get(key, [])
    if isinstance(groups, dict):
        raise DefinitionError(f"[{key}] is now an array of tables: write each group as [[{key}]]")
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise DefinitionError(f"[[{key}]] must be an array of tables")
    result = []
    for i, body in enumerate(groups):
        where = f"{key}[{i}]"
        props, members = _split(body, GROUP_PROPERTIES, where)
        if not members:
            raise DefinitionError(f"{where}: has no entries")
        result.append((_docstring(props.get("_docstring"), f"{where}._docstring"), _base_type(props, where), members))
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


def _base_type(props: Mapping, where: str) -> str:
    value = props.get("_base_type", "i32")
    if not isinstance(value, str) or value not in naming.BASE_C_TYPES:
        raise DefinitionError(f"{where}._base_type must be one of {', '.join(naming.BASE_C_TYPES)}")
    return value


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


def _bit_const_groups(
    groups: list[tuple[str | None, str, list[tuple[str, object]]]]
) -> tuple[BitConstGroup, ...]:
    """A composed mask may name an entry of any earlier group, so the groups are read as one sequence."""
    defined: set[str] = set()
    result = []
    for group_doc, base_type, members in groups:
        consts = []
        for key, entry in members:
            where = f"untyped_bit_const.{key}"
            _identifier(key, where)
            entry, doc, fmt = _unwrap_value(entry, where)
            if _is_int(entry):
                if not 0 <= entry <= 30:
                    raise DefinitionError(f"{where}: bit index must be 0..30 (enumerators must fit int)")
                consts.append(BitConst(key, entry, (), doc, fmt))
            elif isinstance(entry, list) and entry and all(isinstance(p, str) for p in entry):
                for part in entry:
                    if part not in defined:
                        raise DefinitionError(
                            f"{where}: composes unknown constant '{part}' "
                            "(only earlier untyped_bit_const entries)"
                        )
                consts.append(BitConst(key, None, tuple(entry), doc, fmt))
            else:
                raise DefinitionError(
                    f"{where}: must be a bit index or a non-empty list of constant names"
                )
            defined.add(key)
        result.append(BitConstGroup(group_doc, base_type, tuple(consts)))
    return tuple(result)


def _int_entry(key: str, entry: object, where: str, *, base_type: str) -> EnumEntry:
    _identifier(key, where)
    value, doc, fmt = _unwrap_value(entry, where)
    if not _is_int(value) or not _INT32_MIN <= value <= _INT32_MAX:
        raise DefinitionError(f"{where}: value must be an integer in the int32 range")
    if base_type == "u32" and value < 0:
        raise DefinitionError(f"{where}: value must not be negative: its _base_type is u32")
    return EnumEntry(key, value, doc, fmt)


def _string_const(key: str, entry: object) -> StringConst:
    where = f"string_const.{key}"
    _identifier(key, where)
    attrs = _attributes(entry, naked="_value", allowed=frozenset({"_value", "_docstring"}), where=where)
    value = attrs.get("_value")
    if not isinstance(value, str):
        raise DefinitionError(f"{where}: value must be a string")
    if any(c in value for c in '"\\\n'):
        raise DefinitionError(f"{where}: value must not contain '\"', '\\' or a newline")
    return StringConst(key, value, _docstring(attrs.get("_docstring"), f"{where}._docstring"))


def _typed_const(name: str, body: dict) -> TypedConst:
    where = f"typed_const.{name}"
    props, members = _split(body, GROUP_PROPERTIES, where)
    base_type = _base_type(props, where)
    entries = [_int_entry(key, entry, f"{where}.{key}", base_type=base_type) for key, entry in members]
    if not entries:
        raise DefinitionError(f"{where}: has no entries")
    return TypedConst(name, tuple(entries), _docstring(props.get("_docstring"), f"{where}._docstring"), base_type)


def _opaque_ref(name: str, body: dict) -> OpaqueRef:
    where = f"opaque_ref.{name}"
    props, members = _split(body, OPAQUE_PROPERTIES, where)
    if members:
        raise DefinitionError(f"{where}: '{members[0][0]}': an opaque_ref has no members; its properties begin with _")
    for key in ("_ctor", "_dtor"):
        if not isinstance(props.get(key, ""), str):
            raise DefinitionError(f"{where}.{key} must be a function name")
    class_name = props.get("_class", name)
    if not isinstance(class_name, str) or not _IDENTIFIER.match(class_name):
        raise DefinitionError(f"{where}._class must be an identifier")
    _identifier(class_name, f"{where}._class")
    return OpaqueRef(
        name, _docstring(props.get("_docstring"), f"{where}._docstring"), props.get("_ctor"), props.get("_dtor"),
        class_name,
    )


def _check_lifecycles(opaque_refs: list[OpaqueRef], functions: Mapping[str, Function]) -> None:
    classes: dict[str, str] = {}
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
        class_name = naming.upper_camel(o.class_name)
        if class_name in classes:
            raise DefinitionError(f"{where}._class: {class_name} is already the class of opaque_ref.{classes[class_name]}")
        classes[class_name] = o.name


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
        fields.append(Field(key, type_name, _docstring(attrs.get("_docstring"), f"{where}._docstring")))
    if not fields:
        raise DefinitionError(f"struct.{name}: has no fields")
    return Struct(name, tuple(fields), _docstring(props.get("_docstring"), f"struct.{name}._docstring"))


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
        _identifier(key, pwhere, reserved=RESERVED_NAMES | GENERATED_LOCALS)
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
        params.append(
            Param(key, type_name, ref, count_type, optional, _docstring(attrs.get("_docstring"), f"{pwhere}._docstring"))
        )
    names = {p.name for p in params}
    for p in params:
        if p.count_type is not None and naming.count_param(p.name) in names:
            raise DefinitionError(
                f"{where}.{p.name}: its count parameter {naming.count_param(p.name)} is already a parameter"
            )
    return Function(name, returns, tuple(params), _docstring(props.get("_docstring"), f"{where}._docstring"))


def _driver_data(body: object, bit_keys: set[str]) -> DriverData | None:
    if body is None:
        return None
    if not isinstance(body, dict):
        raise DefinitionError("[_driver_data] must be a table")
    _reject_unknown(body, {"_header", "const_pins"}, "_driver_data")
    header = body.get("_header")
    if not isinstance(header, str):
        raise DefinitionError("_driver_data._header must be a string")
    _quote_free(header, "_driver_data._header")
    pins_table = body.get("const_pins", {})
    if not isinstance(pins_table, dict):
        raise DefinitionError("_driver_data.const_pins must be a table")
    pins = []
    for key, macro in pins_table.items():
        where = f"_driver_data.const_pins.{key}"
        if key not in bit_keys:
            raise DefinitionError(f"{where}: pins undefined untyped_bit_const '{key}'")
        if not isinstance(macro, str) or not _IDENTIFIER.match(macro):
            raise DefinitionError(f"{where}: must be a driver macro name")
        pins.append((key, macro))
    return DriverData(header, tuple(pins))


def _check_unique_identifiers(api: Api) -> None:
    """Every generated C identifier, constants and declarations alike, is defined once."""
    ns = api.namespace
    seen = {naming.version_const(ns): "the API version constant"}
    keys = [(c.key, f"untyped_bit_const.{c.key}") for c in api.bit_consts]
    keys += [(c.key, f"untyped_const.{c.key}") for c in api.consts]
    keys += [(c.key, f"string_const.{c.key}") for c in api.string_consts]
    keys += [(e.key, f"typed_const.{t.name}.{e.key}") for t in api.typed_consts for e in t.entries]
    for key, where in keys:
        c_name = naming.const_name(ns, key)
        if c_name in seen:
            raise DefinitionError(f"{where}: constant {c_name} already defined by {seen[c_name]}")
        seen[c_name] = where

    idents = [(naming.type_name(ns, t.name), f"typed_const.{t.name}") for t in api.typed_consts]
    for o in api.opaque_refs:
        where = f"opaque_ref.{o.name}"
        idents += [(naming.type_name(ns, o.name), where), (naming.opaque_struct(ns, o.name), where)]
    idents += [(naming.type_name(ns, s.name), f"struct.{s.name}") for s in api.structs]
    idents += [(naming.function_name(ns, f.name), f"function.{f.name}") for f in api.functions]
    for ident, where in idents:
        if ident in seen:
            raise DefinitionError(f"{where}: C identifier {ident} already defined by {seen[ident]}")
        seen[ident] = where
