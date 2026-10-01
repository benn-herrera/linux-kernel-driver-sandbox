"""The Rust binding: the C header's ABI as a nested `ffi` module linked against the
library, and over it the constants, enums, conversions, re-exported types and one owning
struct per opaque ref that names a constructor, every call returning a `Result`."""

from dataclasses import dataclass, field
from pathlib import Path

from api_gen import naming
from api_gen.emitters import rust
from api_gen.model import (
    Api, BitConst, ClassShape, EnumEntry, Function, Group, Param, duplicate_objections,
    generated_name_objections, named_values, single_bit_entries,
)

LABEL = "rust"

_GENERATED_NAMES = ("raw", "result")
"""The locals every class call binds beside the parameters of the function it wraps: the
C call's `raw` result and that result as the enum, `result`."""
_PRELUDE_NAMES = ("Drop", "Err", "Ok", "Option", "Result", "Some", "String")
"""The prelude names the binding spells unqualified, which a module-scope item would shadow."""
_POINTERS_SAFE = (
    "every pointer argument points at a local or a caller reference that lives for the call, "
    "a slice's length its count; the library keeps no pointer after returning."
)
_SAFETY = f"// SAFETY: the handle came from a successful create and is not yet released; {_POINTERS_SAFE}\n"
_SAFETY_CREATE = f"// SAFETY: {_POINTERS_SAFE}\n"
_METHOD = " " * 4
_BODY = " " * 8


def _through_raw_local(api: Api, p: Param, *, ctor: bool) -> bool:
    """Whether the enum parameter `p` travels through its `<p>_raw` local: reached through
    `_ref`, other than an `out` the caller receives, which is a local of its own name."""
    return p.ref is not None and api.kind(p.type) == "enum" and not _received_out(p, ctor=ctor)


def _received_out(p: Param, *, ctor: bool) -> bool:
    """A non-memory `out` the call writes into a local the caller receives: every one of a
    constructor's, and a method's unless `_optional`, which it takes as an `Option`."""
    return p.type != "memory" and p.ref == "out" and (ctor or not p.optional)


def validate(api: Api) -> list[str]:
    """Every objection the Rust binding has to `api`: a name that is a Rust keyword or
    renders as one in UpperCamel; a name the file renders where rustc's `non_snake_case`
    reaches it that the lint refuses; a field of opaque type; a parameter a class renders
    named like one of `_GENERATED_NAMES` or an enum local its function renders; and a name
    the binding would define twice at module scope, in an enum or in a class."""
    objections = rust.rust_keyword_objections(api)
    objections += rust.camel_keyword_objections([
        *rust.camel_names(api),
        *((f"opaque_ref.{o.name}._class", o.class_name) for o in api.opaque_refs if o.ctor is not None),
    ])

    classes = api.classes()
    groups = [g for g in (*api.bit_const_groups, *api.const_groups) if g.to_string is not None]
    lints = rust.field_names(api)
    lints += [(f"{g.name}._to_string", g.to_string) for g in groups]
    lints += rust.enum_conversion_names(api)
    generated = []
    for shape in classes:
        lints += [(f"function.{fn.name}", fn.name) for fn in shape.methods]
        for fn, params, ctor in shape.class_params():
            raw_locals = [
                (f"function.{fn.name}.{p.name}", naming.rust_raw_local(p.name))
                for p in params
                if _through_raw_local(api, p, ctor=ctor)
            ]
            lints += rust.param_names(fn, params) + raw_locals
            generated += generated_name_objections(
                ((f"function.{fn.name}.{p.name}", p.name) for p in params),
                {*_GENERATED_NAMES, *(local for _, local in raw_locals)},
            )
    objections += rust.snake_case_objections(lints)
    objections += rust.opaque_field_objections(api)
    objections += generated

    module = rust.prelude_names(_PRELUDE_NAMES)
    constants = api.constant_names(enum_entries=False, version=True)
    module += [(where, naming.unprefixed_const_name(name)) for where, name in constants]
    module += [(f"{g.name}._to_string", g.to_string) for g in groups]
    module += rust.module_names(api)
    module += [(f"opaque_ref.{s.opaque.name}._class", naming.upper_camel(s.opaque.class_name)) for s in classes]
    objections += duplicate_objections(module, "module scope")
    objections += rust.enum_member_objections(api)
    for shape in classes:
        own = ["create", "handle", *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {naming.upper_camel(shape.opaque.class_name)}")
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("rust") / f"{name}.rs"


def emit(api: Api, *, source_name: str, name: str, library: str | None, project: str) -> str:
    """The Rust binding, as rustfmt lays it out. `library` is required: the `ffi` module
    links against it."""
    link_name = None if library is None else naming.rust_link_name(library)
    assert link_name is not None, "the generator refuses a Rust binding without a library it can link"
    blocks = [rust.version_constant(api, prefixed=False)]
    blocks += [rust.constant_group(api, g, prefixed=False) + _bit_to_string(g) for g in api.bit_const_groups]
    blocks += [rust.constant_group(api, g, prefixed=False) + _plain_to_string(g) for g in api.const_groups]
    blocks += [rust.string_group(api, g, prefixed=False) for g in api.string_const_groups]
    blocks += [rust.enum_block(t) for t in api.typed_consts]
    blocks.append(rust.reexports(api))
    blocks += [_class(api, shape) for shape in api.classes()]
    return rust.rustfmt(
        f"// GENERATED by vdev/api_gen from {source_name}; do not edit.\n\n"
        + _ffi(api, link_name)
        + "".join("\n" + b for b in blocks)
    )


def _ffi(api: Api, link_name: str) -> str:
    """The `ffi` module: the C header's types under their C names, and every function in
    one `extern` block linked against the library `link_name` names."""
    types = [rust.enum_alias(api, t) for t in api.typed_consts] + rust.type_definitions(api)
    extern = ""
    if api.functions:
        declarations = "\n".join(
            rust.function_docs(fn, indent=_BODY) + _BODY + rust.signature(api, fn, prefix="pub fn ") + ";\n"
            for fn in api.functions
        )
        extern = (
            f'\n    #[link(name = "{link_name}")]\n'
            f'    unsafe extern "C" {{\n{declarations}    }}\n'
        )
    return rust.ffi_module(types, tail=extern)


def _plain_to_string(group: Group[EnumEntry]) -> str:
    """A `match` on the group's constants, one arm per value as `named_values()` names it,
    since a repeated pattern is unreachable and `-D warnings` refuses it."""
    if group.to_string is None:
        return ""
    arms = "".join(
        f'        {k} => "{k}",\n' for k in (naming.unprefixed_const_name(e.name) for e in named_values(group))
    )
    return (
        f"\npub fn {group.to_string}(value: {group.base_type}) -> &'static str {{\n"
        f"    match value {{\n{arms}"
        f'        _ => "{naming.unknown_value_name(None)}",\n'
        "    }\n}\n"
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term."""
    if group.to_string is None:
        return ""
    keys = [naming.unprefixed_const_name(e.name) for e in single_bit_entries(group)]
    flags = "".join(
        f'    if value & {k} != 0 {{\n        text += "|{k}";\n        value &= !{k};\n    }}\n' for k in keys
    )
    mutable = "mut " if keys else ""
    return (
        f"\npub fn {group.to_string}({mutable}value: {group.base_type}) -> String {{\n"
        f'    if value == 0 {{\n        return String::from("{naming.NO_FLAGS}");\n    }}\n'
        "    let mut text = String::new();\n"
        f"{flags}"
        "    if value != 0 {\n"
        '        text += &format!("|{value:#x}");\n'
        "    }\n"
        "    text[1..].to_string()\n"
        "}\n"
    )


def _safe_type(api: Api, type_name: str) -> str:
    """The module-scope spelling of a non-memory type: an enum by its UpperCamel name,
    anything else as `rust.value_type()` spells it."""
    if api.kind(type_name) == "enum":
        return naming.upper_camel(type_name)
    return rust.value_type(api, type_name)


def _wrote(api: Api, fn: Function, p: Param) -> str:
    """The panic message of an enum value `fn` wrote through `p` that the enum does not name."""
    fname = naming.function_name(api.namespace, fn.name)
    return f"{fname} wrote a {p.name} value {naming.type_name(api.namespace, p.type)} does not name"


@dataclass
class _Marshalled:
    """A function's parameters as the safe layer renders them around one C call."""

    params: list[str] = field(default_factory=list)  # the Rust signature's `name: type`
    before: list[str] = field(default_factory=list)  # statements before the call
    args: list[str] = field(default_factory=list)  # the C call's arguments, in order
    after: list[str] = field(default_factory=list)  # statements after a successful result
    outs: list[Param] = field(default_factory=list)  # the outs the call writes into locals
    unchecked: list[str] = field(default_factory=list)  # raw handles the caller vouches for


def _marshal(api: Api, fn: Function, params: tuple[Param, ...], *, ctor: bool) -> _Marshalled:
    """`params` of `fn` as signature parameters, locals, call arguments and the conversions
    after a successful call. A non-memory `out` is a local the call writes and the caller
    receives, unless it is `_optional` outside a constructor, which takes it as an
    `Option`. An enum reached through `_ref` is a reference to the enum, which cannot
    coerce to a pointer to its base type: it travels through a local of that type. An
    opaque by value or `in` is its class by reference where it has one; an opaque the
    library may replace, `out` or `inout`, is the raw handle even where it has a class,
    whose own handle it would orphan. A raw handle the library reads, one without a class
    by value, `in` or `inout` or one with a class `inout`, makes the function unsafe."""
    classes = {shape.opaque.name: naming.upper_camel(shape.opaque.class_name) for shape in api.classes()}
    m = _Marshalled()
    for p in params:
        kind = "memory" if p.type == "memory" else api.kind(p.type)
        if kind == "memory":
            count = naming.count_param(p.name)
            if p.ref == "in" and p.optional:
                m.params.append(f"{p.name}: Option<&[u8]>")
                length = f"{p.name}.map_or(0, <[u8]>::len)"
                m.args.append(f"{p.name}.map_or(core::ptr::null(), <[u8]>::as_ptr).cast()")
            elif p.ref == "in":
                m.params.append(f"{p.name}: &[u8]")
                length = f"{p.name}.len()"
                m.args.append(f"{p.name}.as_ptr().cast()")
            else:
                m.params.append(f"{p.name}: &mut [u8]")
                length = f"{p.name}.len()"
                m.args.append(f"{p.name}.as_mut_ptr().cast()")
            m.before.append(
                f'let {count} = {p.count_type}::try_from({length}).expect("{p.name} is longer than {p.count_type} can count");'
            )
            m.args.append(count)
        elif _received_out(p, ctor=ctor):
            m.before.append(f"let mut {p.name} = {rust.out_default(api, p.type)}();")
            if kind == "enum":
                enum = naming.upper_camel(p.type)
                m.after.append(f'let {p.name} = {enum}::try_from({p.name}).expect("{_wrote(api, fn, p)}");')
            m.args.append(f"&mut {p.name}")
            m.outs.append(p)
        elif _through_raw_local(api, p, ctor=ctor):
            _marshal_enum_ref(api, fn, p, into=m)
        elif kind == "opaque" and p.ref == "in" and p.type in classes:
            if p.optional:
                m.params.append(f"{p.name}: Option<&{classes[p.type]}>")
                m.args.append(f"{p.name}.map_or(core::ptr::null(), |c| &c.handle)")
            else:
                m.params.append(f"{p.name}: &{classes[p.type]}")
                m.args.append(f"&{p.name}.handle")
        elif p.ref is not None:
            if kind == "opaque" and p.ref != "out":
                m.unchecked.append(p.name)
            safe = _safe_type(api, p.type)
            if p.ref == "in":
                m.params.append(f"{p.name}: Option<&{safe}>" if p.optional else f"{p.name}: &{safe}")
                m.args.append(f"{p.name}.map_or(core::ptr::null(), core::ptr::from_ref)" if p.optional else p.name)
            else:
                m.params.append(f"{p.name}: Option<&mut {safe}>" if p.optional else f"{p.name}: &mut {safe}")
                m.args.append(f"{p.name}.map_or(core::ptr::null_mut(), core::ptr::from_mut)" if p.optional else p.name)
        elif kind == "enum":
            m.params.append(f"{p.name}: {naming.upper_camel(p.type)}")
            m.args.append(f"{p.name} as {rust.rust_type(api, p.type, path='ffi::')}")
        elif kind == "opaque" and p.type in classes:
            m.params.append(f"{p.name}: &{classes[p.type]}")
            m.args.append(f"{p.name}.handle")
        else:
            if kind == "opaque":
                m.unchecked.append(p.name)
            m.params.append(f"{p.name}: {_safe_type(api, p.type)}")
            m.args.append(p.name)
    return m


def _marshal_enum_ref(api: Api, fn: Function, p: Param, *, into: _Marshalled) -> None:
    """An enum parameter of `fn` that travels through its `<p>_raw` local: its value
    converted into that local of the base type, passed by address, and for a writable one
    converted back after a successful call. An `_optional` `out` travels as an `inout` does."""
    enum = naming.upper_camel(p.type)
    raw = naming.rust_raw_local(p.name)
    ffi_type = rust.rust_type(api, p.type, path="ffi::")
    back = f'{enum}::try_from({{}}).expect("{_wrote(api, fn, p)}")'
    if p.ref == "in" and p.optional:
        into.params.append(f"{p.name}: Option<&{enum}>")
        into.before.append(f"let {raw} = {p.name}.map(|m| *m as {ffi_type});")
        into.args.append(f"{raw}.as_ref().map_or(core::ptr::null(), core::ptr::from_ref)")
    elif p.ref == "in":
        into.params.append(f"{p.name}: &{enum}")
        into.before.append(f"let {raw} = *{p.name} as {ffi_type};")
        into.args.append(f"&{raw}")
    elif p.optional:
        into.params.append(f"{p.name}: Option<&mut {enum}>")
        into.before.append(f"let mut {raw} = {p.name}.as_deref().map(|m| *m as {ffi_type});")
        into.args.append(f"{raw}.as_mut().map_or(core::ptr::null_mut(), core::ptr::from_mut)")
        into.after.append(f"if let (Some(m), Some(v)) = ({p.name}, {raw}) {{ *m = {back.format('v')}; }}")
    else:
        into.params.append(f"{p.name}: &mut {enum}")
        into.before.append(f"let mut {raw} = *{p.name} as {ffi_type};")
        into.args.append(f"&mut {raw}")
        into.after.append(f"*{p.name} = {back.format(raw)};")


def _checked_call(api: Api, fn: Function, args: list[str], *, safety: str, before: list[str], after: list[str], ok: str) -> str:
    """A method body: `before`, the call under its `safety` comment, the result converted
    and checked, `after`, then `ok`, the success value."""
    fname = naming.function_name(api.namespace, fn.name)
    ret = naming.upper_camel(fn.returns)
    unnamed = f"{fname} returned a value {naming.type_name(api.namespace, fn.returns)} does not name"
    statements = [
        *before,
        safety.rstrip("\n"),
        f"let raw = unsafe {{ ffi::{fname}({', '.join(args)}) }};",
        f'let result = {ret}::try_from(raw).expect("{unnamed}");',
        f"if result != {ret}::{naming.upper_camel(api.success_entry(fn).name)} {{ return Err(result); }}",
        *after,
        ok,
    ]
    return "".join(f"{_BODY}{s}\n" for s in statements)


def _method(api: Api, fn: Function, *, name: str, receiver: list[str], m: _Marshalled, returns: str, body: str) -> str:
    """A method `name` over `fn` with `receiver` before `m`'s parameters, returning
    `Result<returns, R>`, `R` the result enum; unsafe, with a `# Safety` section, where it
    takes a raw handle."""
    safety = [f"`{n}` must be a handle the library issued and has not yet destroyed." for n in m.unchecked]
    qualifier = "pub unsafe fn" if safety else "pub fn"
    params = [*receiver, *m.params]
    return (
        rust.function_docs(fn, safety=safety, indent=_METHOD)
        + rust.many_arguments_allow(len(params), indent=_METHOD)
        + f"{_METHOD}{qualifier} {name}({', '.join(params)}) -> "
        + f"Result<{returns}, {naming.upper_camel(fn.returns)}> {{\n"
        + body
        + f"{_METHOD}}}\n"
    )


def _class(api: Api, shape: ClassShape) -> str:
    ns = api.namespace
    opaque, ctor, dtor, cached = shape.opaque, shape.ctor, shape.dtor, shape.cached
    cls = naming.upper_camel(opaque.class_name)
    handle_type = rust.rust_type(api, opaque.name, path="ffi::")

    fields = "".join(f"    {p.name}: {_safe_type(api, p.type)},\n" for p in cached)
    struct = f"{rust.doc_comment(opaque.docstring)}pub struct {cls} {{\n    handle: {handle_type},\n{fields}}}\n"

    m = _marshal(api, ctor, ctor.params, ctor=True)
    # a ctor out named `handle` initialises the field by shorthand, as clippy requires
    handle = "handle" if shape.handle.name == "handle" else f"handle: {shape.handle.name}"
    ok = f"Ok({cls} {{ {', '.join([handle, *(p.name for p in cached)])} }})"
    members = [
        _method(
            api, ctor, name="create", receiver=[], m=m, returns=cls,
            body=_checked_call(api, ctor, m.args, safety=_SAFETY_CREATE, before=m.before, after=m.after, ok=ok),
        ),
        f"{_METHOD}pub fn handle(&self) -> {handle_type} {{\n{_BODY}self.handle\n{_METHOD}}}\n",
    ]
    members += [
        f"{_METHOD}pub fn {p.name}(&self) -> &{_safe_type(api, p.type)} {{\n{_BODY}&self.{p.name}\n{_METHOD}}}\n"
        if api.kind(p.type) == "struct"
        else f"{_METHOD}pub fn {p.name}(&self) -> {_safe_type(api, p.type)} {{\n{_BODY}self.{p.name}\n{_METHOD}}}\n"
        for p in cached
    ]
    for fn in shape.methods:
        m = _marshal(api, fn, fn.params[1:], ctor=False)
        names = [p.name for p in m.outs]
        if len(names) == 1:
            returns, ok = _safe_type(api, m.outs[0].type), f"Ok({names[0]})"
        else:
            returns, ok = f"({', '.join(_safe_type(api, p.type) for p in m.outs)})", f"Ok(({', '.join(names)}))"
        body = _checked_call(api, fn, ["self.handle", *m.args], safety=_SAFETY, before=m.before, after=m.after, ok=ok)
        members.append(_method(api, fn, name=fn.name, receiver=["&self"], m=m, returns=returns, body=body))
    drop = ""
    if dtor is not None:
        release = _checked_call(
            api, dtor, ["handle"], safety=_SAFETY,
            before=["let handle = self.handle;", "core::mem::forget(self);"], after=[], ok="Ok(())",
        )
        members.append(_method(api, dtor, name="release", receiver=["self"], m=_Marshalled(), returns="()", body=release))
        drop = (
            f"\nimpl Drop for {cls} {{\n{_METHOD}fn drop(&mut self) {{\n{_BODY}if !self.handle.is_null() {{\n"
            f"{_BODY}    {_SAFETY}"
            f"{_BODY}    let _ = unsafe {{ ffi::{naming.function_name(ns, dtor.name)}(self.handle) }};\n"
            f"{_BODY}}}\n{_METHOD}}}\n}}\n"
        )
    return struct + f"\nimpl {cls} {{\n" + "\n".join(members) + "}\n" + drop
