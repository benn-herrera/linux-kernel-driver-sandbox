# THESIS - api_gen

API sync across implementation, exposure, bindings requires the tireless consistency best suited to automation

## A C header is a rotten single source of truth

A C header is an idiomatic expression of an API. Transforming one idiom to another while also imposing artificial restrictions on the usage of the single source of truth coding language introduces unnecessary complexities and gotchas.

## A better way
- A language-neutral DSL and code generator allow for a single authored contract to propagate to all supported languages
- The neutral DSL makes emitting idiomatic code for each target language straightforward and imposes no additional restrictions or burdens on the hand-authored code
- A well-designed, transparent DSL makes contract authoring, reading, editing easy for human or agent authors
- A well-designed generator makes adding support for additional languages straightforward
