# Apply Pricing test-case index

The active scenarios and configurable expected-result rules for all 36 IDs in the updated October 16 design are maintained only in:

- `apply_pricing_framework/rules/expected-results.json`

That catalog maps scenario IDs to Bruno `.bru` payloads, source-backed input preconditions, expected checks, and design references. It is consumed by the framework evaluator and report generator; this index intentionally duplicates no expected values.

Source documents and the design-to-rule comparison are retained in `apply_pricing_framework/design/`. See `apply_pricing_framework/README.md` for framework usage and scenario onboarding. See `bruno/README.md` for running the original Bruno collection.
