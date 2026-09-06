# Architecture

How this adapter is organized, why, and what was deliberately left out. The
compact version lives in `stt.py`'s module docstring; this document is the
full statement for contributors and for the upstream proposal.

## Goals

1. **Minimal core, decoupled extensions** — a small auditable core; every
   capability attaches at a defined seam without interleaving with it.
2. **Honest degradation** — an invalid *combination* never fails silently
   mid-conversation; contracts are checked at composition time.
3. **Single source of truth per fact** — a parameter's request shape, its
   companion requirements, and the response fields it consumes are declared
   in one place; docs mirror code instead of tracking it.
4. **Offline-testable by construction** — pure layers carry no I/O, so their
   behavior is testable without a network or fakes-of-fakes.

## Module map (layers depend downward only)

```
protocol.py        byte framing: client frames, ServerMessage parsing     [pure]
_options.py        options → full-request JSON; apply_updates             [pure]
_capabilities.py   capability descriptors + composition-time checks       [pure]
_transcript.py     TranscriptMapper: result payloads → speech events      [pure]
_utils.py          PeriodicCollector (usage batching)                     [pure]
stt.py             STT + SpeechStream: transport, reconnection, usage     [only
                   module that imports the framework beyond types]         here]
```

`protocol` / `_options` / `_capabilities` import nothing from `livekit`.
`_transcript` knows payloads and events, not sockets. `stt.py` composes the
layers and owns the framework boundary.

## The capability model

A capability is the unit of graduation. Request toggles, companion settings,
and response consumers travel together as one `Capability` descriptor
(`_capabilities.py`) instead of being scattered across the option dataclass,
the mapper, and the docs:

- **requirements** — predicates over the *effective* options (escape hatch
  included). Unmet requirements are reported by `check_capabilities` at
  construction: warning, not raising, because the degraded mode is
  legitimate (e.g. caption-only use with an external VAD).
- **check modes** — `always_check` capabilities (turn detection) are the
  adapter's core expectation and are checked even when untouched; opt-in
  capabilities (speaker separation, metadata tags) are checked only when one
  of their escape-hatch fields appears, so a *partially wired bundle* warns
  instead of silently doing nothing.
- **escape_hatch_fields / consumes** — the graduation ledger: which request
  keys a capability will promote, and which response fields it maps. This is
  the code-side source for the PARAMETERS.md pairing tables.

**Graduation path** (escape hatch → first-class): add the typed option, move
the requirement from `requires_escape` to `requires`, implement the
`consumes` mapping, update the tables. Mechanical, single-capability-sized
diffs; bundles (speaker separation's four settings) graduate as one unit so
companions cannot drift.

## Side effects (every effect paired with its reversal)

- WebSocket connect ↔ per-connection `finally: ws.close()`
- send/recv tasks ↔ `gracefully_cancel` + gathered exception retrieved
- usage accounting ↔ flushed at flush-sentinel, input end, **and** connection
  teardown (accounting survives failure paths — dispose reaches quiescence)
- event emission ↔ one-way by contract; guarded where the channel may close
- utterance state (`TranscriptMapper`) ↔ survives retries *by decision*
  (recognized-before-the-drop text is real); never fabricated after failure —
  `commit_pending` runs only on normal completion

## Combination contract

The service accepts combinations that break this adapter's event semantics
(e.g. `enable_nonstream=False` removes the only source of `definite`). The
registry makes each such constraint explicit and machine-checked; the full
hazard matrix and its rationale are in PARAMETERS.md ("Combination hazards").

## Test taxonomy

| Layer | Test style | Example |
|---|---|---|
| `protocol` | byte-level round-trips vs. the archived official demo | `test_protocol.py` |
| `_options` | payload assertions (defaults, serialization, escape hatch) | `test_request_payload_defaults` |
| `_capabilities` | requirement satisfaction / silence of valid combos | `test_partial_speaker_escape_hatch_warns` |
| `_transcript` | state-machine sequences via the **real** mapper (no fake of it) | `test_empty_definite_still_ends_utterance` |
| `stt` transport | scripted-WebSocket pipelines driving the real `_run` | `test_unexpected_close_raises_retryable_error` |

Fakes mimic only what the layer under test does not own (a scripted ws, a
stub session); the mapper under test is always the production class.

## Deliberately not built (and the trigger to revisit)

| Not built | Why | Revisit when |
|---|---|---|
| DI / service registry (Cordis-style `ctx`) | 33 parameters do not need a container; descriptors + one check call give the same contract discipline | the plugin grows multiple transports (e.g. a batch endpoint) |
| Hook/plugin system in the mapper | v0.2 mappings are 3 call sites; hooks would be indirection without consumers | a second provider-variant mapper exists (cartesia-style split by protocol) |
| Descriptor-driven payload assembly | the request shape is fixed by the protocol; a generic assembler would shadow it | a capability needs computed request fields beyond merge semantics |
| Capability requirements as `raise` | degraded modes are legitimate for caption-only consumers | evidence that agents still misconfigure in production after warnings |

## Growth path (matches ROADMAP.md)

- v0.2 speaker separation: graduate the pre-declared `SPEAKER_SEPARATION`
  bundle (typed options, `requires` swap, `speaker_id` mapping) — registry
  entry already exists.
- v0.2 response batch: `consumes` fields land in `_transcript` (result-level)
  and `stt.py` (payload-level: `audio_info.duration`, `log_id`).
- v0.3 upstream port: module map and test taxonomy translate 1:1 to the
  monorepo's per-plugin layout.

## Upstream drift (when the official docs change)

The protocol facts trace to the archived snapshot in `refs/` (hashed, dated);
re-fetching and diffing it is the detection step. Each change class lands in
exactly one layer per concern:

| Change | Day-0 support | Full support |
|---|---|---|
| new request param | `extra_request_params` (works immediately) | graduate per the capability path; add a registry entry if it has companion constraints |
| changed param semantics | escape hatch can override the first-class value of the same name (merge-last contract, pinned by test) | adapt the single point: payload builder / `protocol.py` / `_transcript.py` |
| changed server default | none needed — explicit-send strategy means our requests never depend on server defaults (unsent optional fields are the exception) | — |
| deleted param (first-class) | fails loudly: the server error frame surfaces as `APIStatusError` | mechanical removal across options/payload/docs/tests |
| deleted param (escape hatch) | user stops passing it; plugin unchanged | — |
| response shape change | visible gap in the PARAMETERS mapping table | mapper fix; E2E fixture diff catches it (unit tests use synthetic payloads — they pin our mapping, not the server's shape) |
| new response data (new param producing new fields) | observable immediately: unrecognized result fields log at debug level (`lk.pii.data` marked), shape inspectable without packet capture | consumer attaches at one of three pre-declared levels — utterance keys in the `TranscriptMapper` utterance loop, result keys around it, payload keys in `stt._handle_server_message`; output goes to a framework slot (`SpeechData.metadata` / `speaker_id` / `language` / `stt_context` / `words`); finish by moving the key from `_KNOWN_DROPPED_RESULT_KEYS` to the consumed set and updating the capability's `consumes` + PARAMETERS tables |

The response-shape row is the weak axis by design until real-response
fixtures from E2E runs are archived; the escape-hatch-override contract is
what makes request-side drift survivable without releases. The last row is
the full lifecycle of a *param + data + consumer* triple — the mapper's two
key sets (`_CONSUMED_RESULT_KEYS` / `_KNOWN_DROPPED_RESULT_KEYS`) are the
code-side ledger of what is consumed, so graduating a consumer is a
mechanical key move plus its mapping code.
