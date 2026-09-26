"""C++ language facts the C++ emitters share: the keywords, and the objection every C++
translation unit that includes the header has to a definition's names."""

from api_gen.emitters import c
from api_gen.model import Api

# Every C++20 keyword and alternative token, the C keywords C++ shares included: the
# wrapper and the stub are C++ translation units that include the C header.
CPP_KEYWORDS = frozenset(
    "alignas alignof and and_eq asm bitand bitor bool catch char8_t char16_t "
    "char32_t class compl concept consteval constexpr constinit const_cast co_await "
    "co_return co_yield decltype delete dynamic_cast explicit export "
    "false friend mutable namespace new noexcept not "
    "not_eq nullptr operator or or_eq private protected public reinterpret_cast requires "
    "static_assert static_cast template this "
    "thread_local throw true try typeid typename using virtual "
    "wchar_t xor xor_eq".split()
) | (c.C_KEYWORDS - {"restrict"})  # restrict is C's alone


def cpp_keyword_objections(api: Api) -> list[str]:
    """Every name that is a C++ keyword, unprefixed by an output: 'C keyword' for one C
    already reserves (the header refuses it too), 'C++ keyword' for one unique to C++."""
    return [
        f"{where}: '{name}' is a {'C' if name in c.C_KEYWORDS else 'C++'} keyword"
        for where, name in api.names()
        if name in CPP_KEYWORDS
    ]
