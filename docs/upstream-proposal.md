# Draft: Volcengine streaming STT plugin for LiveKit Agents

This is a proposal draft, not a submitted upstream issue.

The adapter implements Volcengine's v3 bidirectional streaming ASR API with
standard LiveKit STT events and framework-owned retries. Its standalone layout
separates wire framing, request options, capability checks, and transcript mapping.

Evidence available for review:

- Archived public protocol references with provenance under `refs/`.
- Offline tests for connection errors, end-of-input, option updates, and transcript events.
- A sanitized real-service fixture generated from synthetic Chinese shopping speech.
- Integration testing with an existing LiveKit backend and its native STT fallback adapter.

The initial supported production profile uses 16 kHz mono PCM, ASR 2.0,
two-pass recognition, single-result mode, and speaker separation disabled.
Speaker metadata and other response-side extensions remain explicitly documented
future work; request escape hatches alone are not claims of mapped output support.

Before submitting upstream, adapt the package and tests to the current LiveKit
monorepo contributor requirements and discuss ownership/maintenance expectations.
