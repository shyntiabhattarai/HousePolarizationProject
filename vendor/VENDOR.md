# Vendored files

Files here are downloaded once, never edited, and inlined into the page by `make_artifact.py`.

## plotly-cartesian-4.3.0.min.js

- **URL:** https://cdn.plot.ly/plotly-cartesian-4.3.0.min.js (official Plotly CDN)
- **Version:** plotly.js v4.3.0, the "cartesian" partial bundle: scatter, bar, histogram and the other cartesian trace types. GitHub release `v4.3.0`, published 2026-11-10.
- **Downloaded:** 2026-11-23 15:41:30 CST with `curl -sSfL`
- **Size:** 1516234 bytes
- **SHA-256:** 38d5da8c29f94a5ba9bce10fd48ef0601dfb47bb2490c2e305137993ae7ba175
- **License:** MIT. The file header reads "Copyright 2012-2026, Plotly, Inc. ... Licensed under the MIT license".
- **Why the partial bundle:** the page uses only scatter and bar traces. The full bundle (`plotly-4.3.0.min.js`) is 4.8 MB, and all of it would be inlined.
- **Network note:** the bundle contains one `XMLHttpRequest` reference, in d3's request helper, which runs only if a page asks Plotly to load remote data. This page never does. `tests/test_artifact.py` test 2 checks four things:
  1. The inlined block is byte-identical to this file, and its SHA-256 matches the one above.
  2. Inside the block, `XMLHttpRequest` appears exactly once (`VENDOR_EXCEPTIONS`), and every other forbidden string appears zero times.
  3. Outside the block, no forbidden string appears at all, `XMLHttpRequest` included.
  4. There is no `<script src` anywhere on the page.
