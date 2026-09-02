# Render Plan

Phase 2 establishes deterministic rendering contracts. The production renderer will use FFmpeg with:

- 1080x1920 output
- source-aware scaling and crop
- CFR output
- H.264 video + AAC audio
- configurable CRF/preset
- subtitle burn-in as a separate filter stage
- no repeated lossy intermediate renders

The browser preview must never be treated as the final-quality export.