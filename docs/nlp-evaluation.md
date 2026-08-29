# Lightweight NLP Evaluation

## Decision

Do not add spaCy to the reliable product path. Keep the contextual reply
resolver deterministic and revisit trained NLP only for a measured parsing gap
that cannot be solved safely with question context or catalog grounding.

## Probe

The experiment installed spaCy `3.8.7` and `en_core_web_sm 3.8.0` into an
ignored `.local/` directory. No package, model, or dependency declaration was
committed. The probe directory was removed after measurement.

| Variant | Disk | Standalone memory | Startup | Per message |
|---|---:|---:|---:|---:|
| spaCy blank English | 211 MiB | 79 MiB | 1.02 s | 4.74 microseconds |
| spaCy small trained model | 226 MiB | 119 MiB | 1.02 s | 4.75 milliseconds |
| Deterministic contextual resolver | no new dependency | negligible | negligible | 4.23 microseconds |

Measurements are local Windows probe results, not judging-machine guarantees.

## Capability result

The trained model provided useful generic syntax:

- `Nike` was labeled as an organization;
- negation in `I don't want leather` was attached to `want`;
- `platform heels` produced a compound noun structure.

It did not resolve the shopping-domain decision:

- `7` and `80` were both generic cardinal numbers rather than size and budget;
- `blue/` was incorrectly tagged as a number;
- organization detection did not establish that an entity is a valid catalog
  brand;
- noun/dependency structure did not map subjective needs to catalog attributes.

The immediate question already supplies stronger evidence for these cases. A
catalog-derived brand/category/value linker is therefore a better next
investment than a general-purpose NLP dependency.

## Retention rule

A future NLP component must demonstrate all of the following before adoption:

1. parser-corpus improvement beyond deterministic context and catalog aliases;
2. no material regression in public or target-disjoint metrics;
3. acceptable cold-start, p95 latency, memory, and install footprint;
4. deterministic fallback when the model or asset is absent;
5. explicit disclosure in setup and submission documentation.
