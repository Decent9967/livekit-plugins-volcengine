# Synthetic shopping response fixture

`synthetic-shopping.json` was captured on 2026-09-09 from a real Volcengine
`bigmodel_async` session using the `volc.seedasr.sauc.duration` resource.
The input was generated with Windows Microsoft Huihui Desktop at 16 kHz,
mono, 16-bit PCM, speaking the two sentences asserted by the replay test.
It contains no customer recording. Provider log/request/user identifiers were removed.

The live response uses an object for `result`; the archived September 1 reference
describes a list. Tests cover both. This fixture establishes response shape and
event mapping, not accuracy across accents, noise conditions, or production traffic.
