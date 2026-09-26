"""The header-only C++20 wrapper: the constants, enums and structs under the namespace,
and a move-only class per opaque ref that names a constructor, forwarding inline to
the C functions."""

from api_gen import emit_c, naming
from api_gen.model import Api, BitConst, EnumEntry, Function, Group, OpaqueRef, Param, TypedConst, single_bit_entries

HANDLE_MEMBER = "handle_"
GENERATED_NAMES = ("result", "status", "handle", HANDLE_MEMBER)
"""Every free name the generated text binds or references where a definition parameter's
name is in scope: `create()`'s `result` parameter and `status` local beside the ctor's
parameters, the private constructor's `handle` parameter beside the cached `out`s, and
the `handle_` member every method reads beside its own parameters. A parameter named like
one of these would collide with it or shadow it."""
# Every C++20 keyword and alternative token, the C keywords C++ shares included: the
# wrapper and the stub are C++ translation units that include the C header.
CPP_KEYWORDS = frozenset(
    "alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t "
    "char32_t class compl concept const consteval constexpr constinit const_cast continue co_await "
    "co_return co_yield decltype default delete do double dynamic_cast else enum explicit export "
    "extern false float for friend goto if inline int long mutable namespace new noexcept not "
    "not_eq nullptr operator or or_eq private protected public register reinterpret_cast requires "
    "return short signed sizeof static static_assert static_cast struct switch template this "
    "thread_local throw true try typedef typeid typename union unsigned using virtual void "
    "volatile wchar_t while xor xor_eq".split()
)
LABEL = "wrapper"


def cpp_keyword_objections(api: Api) -> list[str]:
    """Every name that is a C++ keyword, unprefixed by an output: 'C keyword' for one C
    already reserves (the header refuses it too), 'C++ keyword' for one unique to C++.
    Shared by the wrapper and the stub, the two C++ translation units."""
    return [
        f"{where}: '{name}' is a {'C' if name in emit_c.C_KEYWORDS else 'C++'} keyword"
        for where, name in api.names()
        if name in CPP_KEYWORDS
    ]


def validate(api: Api) -> list[str]:
    """Every objection the wrapper has to `api`: a name that is a C++ keyword, a parameter
    named like one of `GENERATED_NAMES`, and a name the wrapper would define twice in the
    namespace, an enum class or a class. Enums' conversions may share a name, since each
    overloads on its own enum class."""
    problems = cpp_keyword_objections(api)
    problems += [
        f"function.{fn.name}.{p.name}: '{p.name}' is a name the generated code uses"
        for fn in api.functions
        for p in fn.params
        if p.name in GENERATED_NAMES
    ]
    classes = [o for o in api.opaque_refs if o.ctor is not None]
    const = naming.unprefixed_const_name
    namespace = [(const(naming.VERSION_KEY), "the API version constant")]
    for kind, entries in (
        ("untyped_bit_const", api.bit_consts),
        ("untyped_const", api.consts),
        ("string_const", api.string_consts),
    ):
        namespace += [(const(c.name), f"{kind}.{c.name}") for c in entries]
    namespace += [(naming.upper_camel(t.name), f"typed_const.{t.name}") for t in api.typed_consts]
    namespace += [(naming.upper_camel(s.name), f"struct.{s.name}") for s in api.structs]
    namespace += [(naming.upper_camel(o.class_name), f"opaque_ref.{o.name}._class") for o in classes]
    namespace += [
        (g.to_string, f"{g.name}._to_string")
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    overloads: dict[str, str] = {}
    for t in api.typed_consts:
        if t.to_string is not None:
            overloads.setdefault(t.to_string, f"typed_const.{t.name}._to_string")
    namespace += overloads.items()
    problems += _duplicates(namespace, f"namespace {api.namespace}")
    for t in api.typed_consts:
        problems += _duplicates(
            [(naming.upper_camel(e.name), f"typed_const.{t.name}.{e.name}") for e in t.entries],
            f"enum class {naming.upper_camel(t.name)}",
        )
    for o in classes:
        cls = naming.upper_camel(o.class_name)
        ctor = _ctor(api, o)
        members = [(m, "the wrapper's own member") for m in (cls, "create", "handle", "release", HANDLE_MEMBER)]
        members += [(f.name, f"function.{f.name}") for f in _methods(api, o)]
        members += [(p.name, f"function.{ctor.name}.{p.name}") for p in _cached(ctor, o)]
        problems += _duplicates(members, f"class {cls}")
    return [f"{LABEL}: {p}" for p in problems]


def wrapper(api: Api, *, source_name: str, stem: str) -> str:
    ns = api.namespace
    std_headers = {"utility"}
    if any(g.to_string is not None for g in api.bit_const_groups):
        std_headers |= {"charconv", "string"}
    if any(g.to_string is not None for g in api.const_groups):
        std_headers.add("string")
    out = [
        f"// GENERATED by vdev/api_gen from {source_name}; do not edit.\n",
        "#pragma once\n\n",
        f'#include "{stem}.h"\n\n',
        "".join(f"#include <{h}>\n" for h in sorted(std_headers)) + "\n",
        f"namespace {ns} {{\n",
    ]

    def constant(c_type: str, name: str) -> str:
        return f"inline constexpr {c_type} {naming.unprefixed_const_name(name)} = {naming.const_name(ns, name)};\n"

    # the header's macros carry each untyped constant's type, so restating it here could only disagree
    runs = [constant("auto", naming.VERSION_KEY)]
    runs += [
        _comment(g.docstring) + "".join(constant("auto", c.name) for c in g.entries) + _bit_to_string(g)
        for g in api.bit_const_groups
    ]
    runs += [
        _comment(g.docstring)
        + "".join(constant("auto", c.name) for c in g.entries)
        + _plain_to_string(g)
        for g in api.const_groups
    ]
    runs += [
        _comment(g.docstring) + "".join(constant("const char*", c.name) for c in g.entries)
        for g in api.string_const_groups
    ]
    out += ["\n" + run for run in runs]
    out += [_enum(api, t) for t in api.typed_consts]
    if api.structs:
        out.append("\n" + "".join(f"using {naming.upper_camel(s.name)} = {naming.type_name(ns, s.name)};\n" for s in api.structs))
    out += [_class(api, o) for o in api.opaque_refs if o.ctor is not None]
    out.append(f"\n}}  // namespace {ns}\n")
    return "".join(out)


def _duplicates(names: list[tuple[str, str]], where: str) -> list[str]:
    """One objection per name that `names`, (name, what defines it) pairs, holds more than
    once, in first-seen order, naming everything that defines it."""
    sources: dict[str, list[str]] = {}
    for name, source in names:
        sources.setdefault(name, []).append(source)
    return [
        f"{where}: {n} would be defined more than once, by {' and '.join(s)}" for n, s in sources.items() if len(s) > 1
    ]


def _ctor(api: Api, opaque: OpaqueRef) -> Function:
    return next(f for f in api.functions if f.name == opaque.ctor)


def _methods(api: Api, opaque: OpaqueRef) -> list[Function]:
    """Functions other than the ctor and dtor whose first parameter is the opaque by value."""
    return [
        f
        for f in api.functions
        if f.name not in (opaque.ctor, opaque.dtor)
        and f.params
        and f.params[0].type == opaque.name
        and f.params[0].ref is None
    ]


def _cached(ctor: Function, opaque: OpaqueRef) -> list[Param]:
    """The ctor's `out` parameters other than the handle, each a member of the object."""
    return [p for p in ctor.params if p.ref == "out" and p.type != opaque.name]


def _enum(api: Api, typed: TypedConst) -> str:
    cls = naming.upper_camel(typed.name)
    entries = "".join(
        f"  {naming.upper_camel(e.name)} = {naming.const_name(api.namespace, e.name)},\n" for e in typed.entries
    )
    text = f"\nenum class [[nodiscard]] {cls} : {naming.BASE_C_TYPES[typed.base_type].c_type} {{\n{entries}}};\n"
    if typed.to_string is not None:
        text += _switch(
            typed.to_string, returns="const char*", param=cls,
            cases=[(f"{cls}::{naming.upper_camel(e.name)}", e) for e in typed.entries],
            unknown=naming.unknown_value_name(typed.name),
        )
    return text


def _plain_to_string(group: Group[EnumEntry]) -> str:
    if group.to_string is None:
        return ""
    return _switch(
        group.to_string, returns="std::string", param=naming.BASE_C_TYPES[group.base_type].c_type,
        cases=[(naming.unprefixed_const_name(e.name), e) for e in group.entries],
        unknown=naming.unknown_value_name(None),
    )


def _switch(name: str, *, returns: str, param: str, cases: list[tuple[str, EnumEntry]], unknown: str) -> str:
    """A value-to-name conversion from (case label, entry) pairs: one case per value, named
    by its last entry, since duplicate case labels do not compile."""
    by_value = {e.value: (label, e) for label, e in cases}
    body = "".join(
        f'    case {label}: return "{naming.unprefixed_const_name(e.name)}";\n' for label, e in by_value.values()
    )
    return (
        f"\ninline {returns} {name}({param} value) {{\n  switch (value) {{\n{body}"
        f'  }}\n  return "{unknown}";\n}}\n'
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term."""
    if group.to_string is None:
        return ""
    flags = "".join(
        f'  if (value & {k}) {{\n    text += "|{k}";\n    value &= ~{k};\n  }}\n'
        for k in (naming.unprefixed_const_name(c.name) for c in single_bit_entries(group))
    )
    return (
        f"\ninline std::string {group.to_string}({naming.BASE_C_TYPES[group.base_type].c_type} value) {{\n"
        f'  if (value == 0) {{\n    return "{naming.NO_FLAGS}";\n  }}\n'
        "  std::string text;\n"
        f"{flags}"
        "  if (value != 0) {\n"
        "    char hex[8];\n"
        "    char* const end = std::to_chars(hex, hex + sizeof(hex), uint32_t(value), 16).ptr;\n"
        '    text += "|0x";\n'
        "    text.append(hex, end);\n"
        "  }\n"
        "  return text.substr(1);\n"
        "}\n"
    )


def _ref_type(api: Api, type_name: str) -> str:
    """C++ spelling of a non-memory type the C side reaches through a pointer or caches:
    the struct alias, else the C type."""
    if api.kind(type_name) == "struct":
        return naming.upper_camel(type_name)
    return emit_c.c_type(api, type_name)


def _marshal(api: Api, params: tuple[Param, ...], *, outrefs_are_locals: bool) -> tuple[list[str], list[str]]:
    """The C++ parameter list and the C call arguments. A `memory` parameter is forwarded
    exactly as the C header declares it, pointer and count; with `outrefs_are_locals`, a
    non-memory out parameter is the caller's local, passed by address and absent from the
    signature (a constructor's cached outrefs; `_optional` never reaches them). An
    `_optional` struct or scalar `in`/`out`/`inout` parameter elsewhere is a pointer,
    forwarded as-is, instead of a reference; defaults are trailing, so it is given
    `= nullptr` only when every parameter after it in the signature has one too."""
    # (can this position default to nullptr, its signature text or None if it has none
    # (a constructor's local outref), the C call argument).
    entries: list[tuple[bool, str | None, str]] = []
    for p in params:
        if p.type == "memory":
            for c_type, name in emit_c.c_params(api, p):
                entries.append((False, f"{c_type} {name}", name))
        elif p.ref == "in":
            if p.optional:
                entries.append((True, f"const {_ref_type(api, p.type)}* {p.name}", p.name))
            else:
                entries.append((False, f"const {_ref_type(api, p.type)}& {p.name}", f"&{p.name}"))
        elif p.ref is not None:
            local_outref = outrefs_are_locals and p.ref == "out"
            if local_outref:
                entries.append((False, None, f"&{p.name}"))
            elif p.optional:
                entries.append((True, f"{_ref_type(api, p.type)}* {p.name}", p.name))
            else:
                entries.append((False, f"{_ref_type(api, p.type)}& {p.name}", f"&{p.name}"))
        elif api.kind(p.type) == "enum":
            entries.append((False, f"{naming.upper_camel(p.type)} {p.name}", f"{emit_c.c_type(api, p.type)}({p.name})"))
        else:
            entries.append((False, f"{_ref_type(api, p.type)} {p.name}", p.name))

    sig: list[str] = []
    can_default = True
    for can_be_default, text, _ in reversed(entries):
        if text is None:
            continue
        if can_be_default and can_default:
            sig.append(f"{text} = nullptr")
        else:
            sig.append(text)
            can_default = False
    sig.reverse()
    return sig, [call for _, _, call in entries]


def _doc(fn: Function) -> str:
    return "".join(f"  // {line}\n" for doc in fn.docs() for line in doc.splitlines())


def _c_call(api: Api, fn: Function, args: list[str]) -> str:
    ret = naming.upper_camel(fn.returns)
    return f"{ret}({naming.function_name(api.namespace, fn.name)}({', '.join(args)}))"


def _class(api: Api, opaque: OpaqueRef) -> str:
    cls = naming.upper_camel(opaque.class_name)
    handle_type = naming.type_name(api.namespace, opaque.name)
    ctor = _ctor(api, opaque)
    dtor = next((f for f in api.functions if f.name == opaque.dtor), None)
    methods = _methods(api, opaque)
    handle = next(p for p in ctor.params if p.type == opaque.name and p.ref == "out")
    cached = _cached(ctor, opaque)

    ret = naming.upper_camel(ctor.returns)
    zero = next(e for e in next(t for t in api.typed_consts if t.name == ctor.returns).entries if e.value == 0)
    sig, call = _marshal(api, ctor.params, outrefs_are_locals=True)
    locals_ = "".join(f"    {_ref_type(api, p.type)} {p.name}{{}};\n" for p in ctor.params if p.ref == "out")
    failure = f"{cls}({', '.join(['nullptr', *('{}' for _ in cached)])})"
    create = (
        f"{_doc(ctor)}"
        f"  [[nodiscard]] static {cls} create({', '.join([*sig, f'{ret}* result = nullptr'])}) {{\n"
        f"{locals_}"
        f"    const {ret} status = {_c_call(api, ctor, call)};\n"
        f"    if (result) {{\n      *result = status;\n    }}\n"
        f"    if (status != {ret}::{naming.upper_camel(zero.name)}) {{\n      return {failure};\n    }}\n"
        f"    return {cls}({', '.join([handle.name, *(p.name for p in cached)])});\n"
        "  }\n"
    )

    release_guard = f"      if ({HANDLE_MEMBER}) {{\n        (void)release();\n      }}\n" if dtor is not None else ""
    reassign = "".join(f"      {p.name}_ = other.{p.name}_;\n" for p in cached)
    lifetime = (
        f"\n  {cls}(const {cls}&) = delete;\n"
        f"  {cls}& operator=(const {cls}&) = delete;\n"
        f"  {cls}({cls}&& other) noexcept\n"
        f"      : {', '.join([*(f'{p.name}_(other.{p.name}_)' for p in cached), f'{HANDLE_MEMBER}(std::exchange(other.{HANDLE_MEMBER}, nullptr))'])} {{}}\n"
        f"  {cls}& operator=({cls}&& other) noexcept {{\n"
        f"    if (this != &other) {{\n"
        f"{release_guard}"
        f"      {HANDLE_MEMBER} = std::exchange(other.{HANDLE_MEMBER}, nullptr);\n"
        f"{reassign}"
        f"    }}\n    return *this;\n  }}\n"
    )
    if dtor is not None:
        lifetime += (
            f"  ~{cls}() {{\n    if ({HANDLE_MEMBER}) {{\n      (void)release();\n    }}\n  }}\n"
        )
    lifetime += (
        f"\n  explicit operator bool() const {{ return {HANDLE_MEMBER} != nullptr; }}\n"
        f"  {handle_type} handle() const {{ return {HANDLE_MEMBER}; }}\n"
    )

    body = []
    for fn in methods:
        msig, mcall = _marshal(api, fn.params[1:], outrefs_are_locals=False)
        body.append(
            f"\n{_doc(fn)}  {naming.upper_camel(fn.returns)} {fn.name}({', '.join(msig)}) {{\n"
            f"    return {_c_call(api, fn, [HANDLE_MEMBER, *mcall])};\n  }}\n"
        )
    if dtor is not None:
        body.append(
            f"\n{_doc(dtor)}  {naming.upper_camel(dtor.returns)} release() {{\n"
            f"    return {_c_call(api, dtor, [f'std::exchange({HANDLE_MEMBER}, nullptr)'])};\n  }}\n"
        )

    accessors = "".join(
        f"  const {_ref_type(api, p.type)}& {p.name}() const {{ return {p.name}_; }}\n"
        if api.kind(p.type) == "struct"
        else f"  {_ref_type(api, p.type)} {p.name}() const {{ return {p.name}_; }}\n"
        for p in cached
    )
    private_members = "".join(f"  {_ref_type(api, p.type)} {p.name}_;\n" for p in cached)
    ctor_params = ", ".join([f"{handle_type} handle", *(f"const {_ref_type(api, p.type)}& {p.name}" for p in cached)])
    inits = ", ".join([*(f"{p.name}_({p.name})" for p in cached), f"{HANDLE_MEMBER}(handle)"])
    return (
        f"\n{_comment(opaque.docstring)}class {cls} {{\n public:\n{create}{lifetime}{''.join(body)}"
        + (f"\n{accessors}" if accessors else "")
        + f"\n private:\n  {cls}({ctor_params}) : {inits} {{}}\n\n{private_members}  {handle_type} {HANDLE_MEMBER};\n}};\n"
    )


def _comment(doc: str | None) -> str:
    return "".join(f"// {line}\n" for line in doc.splitlines()) if doc else ""
