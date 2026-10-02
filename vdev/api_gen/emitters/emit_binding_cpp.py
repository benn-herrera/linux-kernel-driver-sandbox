"""The header-only C++20 wrapper: the constants, enums and structs under the namespace,
and a move-only class per opaque ref that names a constructor, forwarding inline to
the C functions."""

from pathlib import Path

from api_gen import naming
from api_gen.emitters import c, cpp
from api_gen.model import (
    Api, BitConst, ClassShape, EnumEntry, Function, Group, Param, TypedConst, duplicate_objections,
    generated_name_objections, headed, named_values, single_bit_entries,
)

_HANDLE_MEMBER = "handle_"
_GENERATED_NAMES = ("result", "status", "handle", _HANDLE_MEMBER)
"""The fixed names the class's generated text binds where a definition parameter's name is
in scope: `create()`'s `result` parameter and `status` local beside the ctor's parameters,
the private constructor's `handle` parameter beside the cached `out`s, and the `handle_`
member every method reads beside its own parameters. A parameter named like one of these
would collide with it or shadow it; `_rendered_names()` holds the ones the definition
names."""
LABEL = "wrapper"


def _rendered_names(api: Api) -> set[str]:
    """Every name the class's generated text spells where a definition parameter or member
    name is in scope: the C functions it calls, the C typedefs and fixed-width types its
    signatures name, and the namespace's enum classes, boxed scalar and struct aliases and
    classes."""
    ns = api.namespace
    names = {naming.function_name(ns, f.name) for f in api.functions}
    names |= {naming.type_name(ns, t.name) for t in (*api.typed_consts, *api.opaque_refs, *api.boxed_scalars, *api.structs)}
    names |= {naming.upper_camel(t.name) for t in (*api.typed_consts, *api.boxed_scalars, *api.structs)}
    names |= {naming.upper_camel(shape.opaque.class_name) for shape in api.classes()}
    return names | set(naming.BUILTIN_C_TYPES.values())


def validate(api: Api) -> list[str]:
    """Every objection the wrapper has to `api`: a name that is a C++ keyword, a parameter
    named like a type the header's declarations spell, a parameter a class renders named
    like one of `_GENERATED_NAMES` or `_rendered_names()`, a method named like one of the
    latter, and a name the wrapper would define twice in the namespace, an enum class or a
    class. Enums' conversions may share a name, since each overloads on its own enum class."""
    objections = cpp.cpp_keyword_objections(api) + c.parameter_type_objections(api)
    classes = api.classes()
    rendered_names = _rendered_names(api)
    params = [
        (f"function.{fn.name}.{p.name}", p.name)
        for shape in classes
        for fn, rendered, _ in shape.class_params()
        for p in rendered
    ]
    objections += generated_name_objections(params, {*_GENERATED_NAMES, *(rendered_names - c.type_names(api))})
    methods = [(f"function.{fn.name}", fn.name) for shape in classes for fn in shape.methods]
    objections += generated_name_objections(methods, rendered_names)
    const = naming.unprefixed_const_name
    namespace = [(where, const(name)) for where, name in api.constant_names(enum_entries=False, version=True)]
    namespace += [(f"typed_const.{t.name}", naming.upper_camel(t.name)) for t in api.typed_consts]
    namespace += [(f"boxed_scalar.{b.name}", naming.upper_camel(b.name)) for b in api.boxed_scalars]
    namespace += [(f"struct.{s.name}", naming.upper_camel(s.name)) for s in api.structs]
    namespace += [(f"opaque_ref.{s.opaque.name}._class", naming.upper_camel(s.opaque.class_name)) for s in classes]
    namespace += [
        (f"{g.name}._to_string", g.to_string)
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    overloads: dict[str, str] = {}
    for t in api.typed_consts:
        if t.to_string is not None:
            overloads.setdefault(t.to_string, f"typed_const.{t.name}._to_string")
    namespace += [(where, name) for name, where in overloads.items()]
    objections += duplicate_objections(namespace, f"namespace {api.namespace}")
    for t in api.typed_consts:
        objections += duplicate_objections(
            [(f"typed_const.{t.name}.{e.name}", naming.upper_camel(e.name)) for e in t.entries],
            f"enum class {naming.upper_camel(t.name)}",
        )
    for shape in classes:
        cls = naming.upper_camel(shape.opaque.class_name)
        own = [cls, "create", "handle", _HANDLE_MEMBER, *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {cls}")
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("include") / project / f"{name}.hpp"


def emit(api: Api, *, source_name: str, name: str, library: str | None, project: str) -> str:
    """The header-only C++ wrapper."""
    ns = api.namespace
    std_headers = {"utility"}
    if any(g.to_string is not None for g in api.bit_const_groups):
        std_headers |= {"charconv", "string"}
    if any(g.to_string is not None for g in api.const_groups):
        std_headers.add("string")
    out = [
        f"// GENERATED by vdev/api_gen from {source_name}; do not edit.\n",
        "#pragma once\n\n",
        f'#include "{name}.h"\n\n',
        "".join(f"#include <{h}>\n" for h in sorted(std_headers)) + "\n",
        f"namespace {ns} {{\n",
    ]

    def constant(c_type: str, name: str) -> str:
        return f"inline constexpr {c_type} {naming.unprefixed_const_name(name)} = {naming.const_name(ns, name)};\n"

    # the header's macros carry each untyped constant's type, so restating it here could only disagree
    runs = [constant("auto", naming.VERSION_KEY)]
    runs += [
        _comment(g.docstring) + "".join(constant("auto", entry.name) for entry in g.entries) + _bit_to_string(g)
        for g in api.bit_const_groups
    ]
    runs += [
        _comment(g.docstring)
        + "".join(constant("auto", entry.name) for entry in g.entries)
        + _plain_to_string(g)
        for g in api.const_groups
    ]
    runs += [
        _comment(g.docstring) + "".join(constant("const char*", entry.name) for entry in g.entries)
        for g in api.string_const_groups
    ]
    out += ["\n" + run for run in runs]
    out += ["\n" + _comment(h) + _enum(api, t) for h, t in headed(api.typed_const_groups)]
    aliased = [*headed(api.boxed_scalar_groups), *headed(api.struct_groups)]
    if aliased:
        out.append("\n" + "".join(
            f"{_comment(h)}using {naming.upper_camel(t.name)} = {naming.type_name(ns, t.name)};\n" for h, t in aliased
        ))
    classes = api.classes()
    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    out += [_class(api, shape, heading=opaque_headings[shape.opaque.name]) for shape in classes]
    out.append(f"\n}}  // namespace {ns}\n")
    return "".join(out)


def _enum(api: Api, typed: TypedConst) -> str:
    cls = naming.upper_camel(typed.name)
    entries = "".join(
        f"  {naming.upper_camel(e.name)} = {naming.const_name(api.namespace, e.name)},\n" for e in typed.entries
    )
    text = f"enum class [[nodiscard]] {cls} : {naming.BASE_C_TYPES[typed.base_type].c_type} {{\n{entries}}};\n"
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
        cases=[(naming.unprefixed_const_name(e.name), e) for e in named_values(group)],
        unknown=naming.unknown_value_name(None),
    )


def _switch(name: str, *, returns: str, param: str, cases: list[tuple[str, EnumEntry]], unknown: str) -> str:
    """A value-to-name conversion from (case label, entry) pairs, one per value: duplicate
    case labels do not compile, so a plain group's come from `named_values()`."""
    body = "".join(f'    case {label}: return "{naming.unprefixed_const_name(e.name)}";\n' for label, e in cases)
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
        for k in (naming.unprefixed_const_name(entry.name) for entry in single_bit_entries(group))
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
    the boxed scalar or struct alias, else the C type."""
    if api.kind(type_name) in ("boxed", "struct"):
        return naming.upper_camel(type_name)
    return c.c_type(api, type_name)


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
            for c_type, name in c.c_params(api, p):
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
            entries.append((False, f"{naming.upper_camel(p.type)} {p.name}", f"{c.c_type(api, p.type)}({p.name})"))
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


def _doc(fn: Function, heading: str | None) -> str:
    """`heading`, the docstring of the group `fn` is the first of in its class, then `fn`'s own."""
    return "".join(_comment(doc, indent="  ") for doc in [heading, *fn.docs()])


def _c_call(api: Api, fn: Function, args: list[str]) -> str:
    ret = naming.upper_camel(fn.returns)
    return f"{ret}({naming.function_name(api.namespace, fn.name)}({', '.join(args)}))"


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class under `heading`, its opaque ref's group docstring where it is the first of
    that group's classes, each of its functions under its own group's where it is the first
    of that group's here."""
    opaque, ctor, dtor, cached = shape.opaque, shape.ctor, shape.dtor, shape.cached
    cls = naming.upper_camel(opaque.class_name)
    handle_type = naming.type_name(api.namespace, opaque.name)
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}

    ret = naming.upper_camel(ctor.returns)
    zero = api.success_entry(ctor)
    sig, call = _marshal(api, ctor.params, outrefs_are_locals=True)
    locals_ = "".join(f"    {_ref_type(api, p.type)} {p.name}{{}};\n" for p in ctor.params if p.ref == "out")
    failure = f"{cls}({', '.join(['nullptr', *('{}' for _ in cached)])})"
    create = (
        f"{_doc(ctor, headings[ctor.name])}"
        f"  [[nodiscard]] static {cls} create({', '.join([*sig, f'{ret}* result = nullptr'])}) {{\n"
        f"{locals_}"
        f"    const {ret} status = {_c_call(api, ctor, call)};\n"
        f"    if (result) {{\n      *result = status;\n    }}\n"
        f"    if (status != {ret}::{naming.upper_camel(zero.name)}) {{\n      return {failure};\n    }}\n"
        f"    return {cls}({', '.join([shape.handle.name, *(p.name for p in cached)])});\n"
        "  }\n"
    )

    release_guard = f"      if ({_HANDLE_MEMBER}) {{\n        (void)release();\n      }}\n" if dtor is not None else ""
    member = naming.cpp_member
    reassign = "".join(f"      {member(p.name)} = other.{member(p.name)};\n" for p in cached)
    lifetime = (
        f"\n  {cls}(const {cls}&) = delete;\n"
        f"  {cls}& operator=(const {cls}&) = delete;\n"
        f"  {cls}({cls}&& other) noexcept\n"
        f"      : {', '.join([*(f'{member(p.name)}(other.{member(p.name)})' for p in cached), f'{_HANDLE_MEMBER}(std::exchange(other.{_HANDLE_MEMBER}, nullptr))'])} {{}}\n"
        f"  {cls}& operator=({cls}&& other) noexcept {{\n"
        f"    if (this != &other) {{\n"
        f"{release_guard}"
        f"      {_HANDLE_MEMBER} = std::exchange(other.{_HANDLE_MEMBER}, nullptr);\n"
        f"{reassign}"
        f"    }}\n    return *this;\n  }}\n"
    )
    if dtor is not None:
        lifetime += (
            f"  ~{cls}() {{\n    if ({_HANDLE_MEMBER}) {{\n      (void)release();\n    }}\n  }}\n"
        )
    lifetime += (
        f"\n  explicit operator bool() const {{ return {_HANDLE_MEMBER} != nullptr; }}\n"
        f"  {handle_type} handle() const {{ return {_HANDLE_MEMBER}; }}\n"
    )

    body = []
    for fn in shape.methods:
        msig, mcall = _marshal(api, fn.params[1:], outrefs_are_locals=False)
        body.append(
            f"\n{_doc(fn, headings[fn.name])}  {naming.upper_camel(fn.returns)} {fn.name}({', '.join(msig)}) {{\n"
            f"    return {_c_call(api, fn, [_HANDLE_MEMBER, *mcall])};\n  }}\n"
        )
    if dtor is not None:
        body.append(
            f"\n{_doc(dtor, headings[dtor.name])}  {naming.upper_camel(dtor.returns)} release() {{\n"
            f"    return {_c_call(api, dtor, [f'std::exchange({_HANDLE_MEMBER}, nullptr)'])};\n  }}\n"
        )

    accessors = "".join(
        f"  const {_ref_type(api, p.type)}& {p.name}() const {{ return {member(p.name)}; }}\n"
        if api.kind(p.type) == "struct"
        else f"  {_ref_type(api, p.type)} {p.name}() const {{ return {member(p.name)}; }}\n"
        for p in cached
    )
    private_members = "".join(f"  {_ref_type(api, p.type)} {member(p.name)};\n" for p in cached)
    ctor_params = ", ".join([f"{handle_type} handle", *(f"const {_ref_type(api, p.type)}& {p.name}" for p in cached)])
    inits = ", ".join([*(f"{member(p.name)}({p.name})" for p in cached), f"{_HANDLE_MEMBER}(handle)"])
    return (
        f"\n{_comment(heading)}{_comment(opaque.docstring)}class {cls} {{\n public:\n{create}{lifetime}{''.join(body)}"
        + (f"\n{accessors}" if accessors else "")
        + f"\n private:\n  {cls}({ctor_params}) : {inits} {{}}\n\n{private_members}  {handle_type} {_HANDLE_MEMBER};\n}};\n"
    )


def _comment(doc: str | None, *, indent: str = "") -> str:
    return f"{indent}// {doc}\n" if doc else ""
