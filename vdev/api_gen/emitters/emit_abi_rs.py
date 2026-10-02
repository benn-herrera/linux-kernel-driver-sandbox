"""The Rust ABI relay: the C header's ABI as `no_mangle` functions, each relaying its call
to the implementation's `crate::f` through values the relay owns, regenerated with the
definition while the implementation behind it is written by hand."""

from pathlib import Path

from api_gen import naming
from api_gen.emitters import c, rust
from api_gen.model import Api, Function, Param, WrappedApi, duplicate_objections, generated_name_objections, headed

LABEL = "rust_abi"

_SAFETY = (
    "Every pointer argument must be null or valid for the call as the C header declares it, "
    "no buffer may overlap another argument of the same call, "
    "and no other thread may read or write a buffer argument during the call. "
    "A panic in the implementation aborts the process."
)
_HELPERS = {"in": "c_bytes", "inout": "c_bytes_mut", "out": "c_bytes_zeroed"}
"""The buffer helper each `memory` `_ref` goes through: the name its `_HELPER_TEXT` defines,
which a rename changes in both."""
_LEN_HELPER = "c_len"
"""The count check every buffer helper calls, emitted with the first of them: the name
`_LEN_TEXT` defines and each `_HELPER_TEXT` calls, which a rename changes in all four."""
_GENERATED_NAMES = ("result",)
"""The local a relay function binds its implementation's result to before the write-backs,
which then reach each `out` and `inout` pointer parameter by its name."""
_PRELUDE_NAMES = ("Err", "None", "Ok", "Option", "Result", "Some")
"""The prelude names the relay spells unqualified, which a module-scope item would shadow."""

_LEN_TEXT = """/// A C byte count as a slice length: `None` below zero or above `isize::MAX`.
fn c_len(count: impl core::convert::TryInto<isize>) -> Option<usize> {
    usize::try_from(count.try_into().ok()?).ok()
}
"""
_HELPER_TEXT = {
    "in": """/// A C `in` buffer as the implementation's slice: `None` for a null pointer or a count above
/// `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for reads of `count` bytes while the slice lives.
unsafe fn c_bytes<'a>(
    ptr: *const core::ffi::c_void,
    count: impl core::convert::TryInto<isize>,
) -> Option<&'a [u8]> {
    let len = c_len(count)?;
    if ptr.is_null() {
        return None;
    }
    Some(unsafe { core::slice::from_raw_parts(ptr.cast(), len) })
}
""",
    "inout": """/// A C `inout` buffer as the implementation's slice: `None` for a null pointer or a count above
/// `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for reads and writes of `count` initialised bytes while the slice
/// lives.
unsafe fn c_bytes_mut<'a>(
    ptr: *mut core::ffi::c_void,
    count: impl core::convert::TryInto<isize>,
) -> Option<&'a mut [u8]> {
    let len = c_len(count)?;
    if ptr.is_null() {
        return None;
    }
    Some(unsafe { core::slice::from_raw_parts_mut(ptr.cast(), len) })
}
""",
    "out": """/// A C `out` buffer as the implementation's slice, zero-filled first, since the caller's memory
/// may be uninitialised: `None` for a null pointer or a count above `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for writes of `count` bytes while the slice lives.
unsafe fn c_bytes_zeroed<'a>(
    ptr: *mut core::ffi::c_void,
    count: impl core::convert::TryInto<isize>,
) -> Option<&'a mut [u8]> {
    let len = c_len(count)?;
    if ptr.is_null() {
        return None;
    }
    let ptr = ptr.cast::<u8>();
    unsafe { ptr.write_bytes(0, len) };
    Some(unsafe { core::slice::from_raw_parts_mut(ptr, len) })
}
""",
}


def validate(api: Api) -> list[str]:
    """Every objection the relay has to `api`: a name that is a Rust keyword or renders as
    one in UpperCamel; a field, enum conversion, parameter, `p_count` or `<p>_local`
    rustc's `non_snake_case` refuses; a field of opaque type; a parameter the relay writes
    back named like one of `_GENERATED_NAMES`, or any named like another parameter's local;
    and a name the relay would define twice at module scope or in an enum."""
    objections = rust.rust_keyword_objections(api) + rust.camel_keyword_objections(rust.camel_names(api))
    lints = rust.field_names(api) + rust.enum_conversion_names(api)
    generated = []
    for fn in api.functions:
        pointers = [p for p in fn.params if p.ref is not None]
        locals_ = [(f"function.{fn.name}.{p.name}", naming.rust_local(p.name)) for p in pointers]
        lints += rust.param_names(fn, fn.params) + locals_
        generated += generated_name_objections(
            ((f"function.{fn.name}.{p.name}", p.name) for p in fn.params),
            {local for _, local in locals_},
        )
        generated += generated_name_objections(
            ((f"function.{fn.name}.{p.name}", p.name) for p in pointers if _written_back(p)), _GENERATED_NAMES
        )
    objections += rust.snake_case_objections(lints)
    objections += rust.opaque_field_objections(api)
    objections += generated
    module = rust.prelude_names(_PRELUDE_NAMES) + rust.module_names(api)
    module += [("the relay's buffer helper", name) for name in (_LEN_HELPER, *_HELPERS.values())]
    module += [(f"function.{fn.name}", naming.function_name(api.namespace, fn.name)) for fn in api.functions]
    objections += duplicate_objections(module, "module scope")
    objections += rust.enum_member_objections(api)
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("rust") / rust.abi_file_name(name)


def emit(api: Api, *, source_name: str, name: str, library: str | None, project: str) -> str:
    """The relay, as rustfmt lays it out."""
    blocks = rust.enum_blocks(api)
    blocks.append(rust.reexports(api))
    refs = {p.ref for fn in api.functions for p in fn.params if p.type == "memory"}
    helpers = [text for ref, text in _HELPER_TEXT.items() if ref in refs]
    blocks += [_LEN_TEXT, *helpers] if helpers else []
    blocks += [rust.group_comment(h) + _relay(api, fn) for h, fn in headed(api.function_groups)]
    if api.wrapped_api is not None:
        blocks.append(_pins(api.namespace, api.wrapped_api))
    return rust.rustfmt(
        f"// GENERATED by vdev/api_gen from {source_name}; do not edit.\n\n"
        + rust.ffi_module([*_constants(api), *rust.type_definitions(api)])
        + "".join("\n" + b for b in blocks)
    )


def _constants(api: Api) -> list[str]:
    """Every constant as `pub const`, C-named, one block each for the version, each bit
    group, each plain group, each enum (its alias, then its entries) and each string group."""
    ns = api.namespace
    blocks = [rust.version_constant(api, prefixed=True)]
    blocks += [rust.constant_group(api, g, prefixed=True) for g in (*api.bit_const_groups, *api.const_groups)]
    for heading, t in headed(api.typed_const_groups):
        alias = naming.type_name(ns, t.name)
        blocks.append(
            rust.group_comment(heading)
            + rust.enum_alias(api, t)
            + "".join(
                f"{rust.doc_comment(e.docstring)}pub const {naming.const_name(ns, e.name)}: {alias} = "
                f"{c.int_literal(e.value, e.format)};\n"
                for e in t.entries
            )
        )
    blocks += [rust.string_group(api, g, prefixed=True) for g in api.string_const_groups]
    return blocks


def _written_back(p: Param) -> bool:
    """Whether the relay writes `p`'s local back through it after the call: a non-memory
    `out` or `inout`."""
    return p.type != "memory" and p.ref in ("out", "inout")


def _relay(api: Api, fn: Function) -> str:
    """One export: a local per pointer parameter, `None` where the pointer is null, read
    from the caller for `in` and `inout` and a default for `out`; the implementation
    pinned to its exact signature through a `fn` pointer, so a borrow that outlives the
    call, an `unsafe fn` or a changed signature fails to compile there, and called; each
    non-null `out` and `inout` written back; its result as the C enum."""
    before, args, after = [], [], []
    for p in fn.params:
        local = naming.rust_local(p.name)
        if p.type == "memory":
            before.append(f"let {local} = unsafe {{ self::{_HELPERS[p.ref]}({p.name}, {naming.count_param(p.name)}) }};")
            args.append(local)
        elif p.ref is None:
            args.append(p.name)
        elif p.ref == "in":
            before.append(f"let {local} = (!{p.name}.is_null()).then(|| unsafe {{ {p.name}.read() }});")
            args.append(f"{local}.as_ref()")
        else:
            start = f"|| unsafe {{ {p.name}.read() }}" if p.ref == "inout" else rust.out_default(api, p.type)
            before.append(f"let mut {local} = (!{p.name}.is_null()).then({start});")
            args.append(f"{local}.as_mut()")
            after.append(f"if let Some({local}) = {local} {{ unsafe {{ {p.name}.write({local}) }}; }}")
    success = naming.const_name(api.namespace, api.success_entry(fn).name)
    pinned = ", ".join(rust.implementation_type(api, p) for p in fn.params)
    statements = [
        *before,
        # on every pin, since clippy's type_complexity score cannot be predicted from here
        "#[allow(clippy::type_complexity)]",
        f"const IMPLEMENTATION: fn({pinned}) -> Result<(), {naming.upper_camel(fn.returns)}> = crate::{fn.name};",
        f"let result = IMPLEMENTATION({', '.join(args)});",
        *after,
        f"match result {{ Ok(()) => ffi::{success}, Err(e) => e as {rust.rust_type(api, fn.returns, path='ffi::')}, }}",
    ]
    return (
        rust.function_docs(fn, extra=[f"{p.name}: may be null" for p in fn.params if p.optional], safety=[_SAFETY])
        + "#[unsafe(no_mangle)]\n"
        + rust.signature(api, fn, prefix='pub unsafe extern "C" fn ', path="ffi::")
        + " {\n"
        + "".join(f"    {s}\n" for s in statements)
        + "}\n"
    )


def _pins(namespace: str, wrapped_api: WrappedApi) -> str:
    """The `wrapped_api` module, `bindgen`'s rendering of the wrapped API's C headers, those
    `_headers` names, which the build writes into `OUT_DIR`, then one compile-time assertion
    per pin against it, both sides widened to `i64` so a macro bindgen types wider cannot truncate into a false match."""
    asserts = "".join(
        f'const _: () = assert!(ffi::{name} as i64 == wrapped_api::{macro} as i64, "{name} must match {macro}");\n'
        for name, macro in ((naming.const_name(namespace, key), macro) for key, macro in wrapped_api.pins)
    )
    return (
        "// Pins to the wrapped API: the implementation build fails if a pinned constant disagrees with its header\n"
        "pub mod wrapped_api {\n"
        "    #![allow(dead_code, non_camel_case_types, non_snake_case, non_upper_case_globals)]\n"
        '    include!(concat!(env!("OUT_DIR"), "/wrapped_api.rs"));\n'
        "}\n"
        f"\n{asserts}"
    )
