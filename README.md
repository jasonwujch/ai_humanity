# 徐乃昌日记 知识图谱 (alpha)

Static SPA exploring an LLM-extracted knowledge graph from Xu Naichang's diary (1920–1922 currently). Inspired by [baojie/shiji-kb](https://github.com/baojie/shiji-kb).

**Live alpha:** https://jasonwujch.github.io/ai_humanity/

## Tabs

- **总览** — node/edge counts, entity-type & relation breakdowns
- **账单** — sortable transaction table with counterparty chips (click → profile)
- **人物关系** — Cytoscape graph, dedup'd by canonical name, filter by degree / relation / confidence
- **作者行迹** — Leaflet map of Xu's `拜访`/`位于` edges over Jiangnan cities
- **实体索引** — wiki-style index across all 9 entity types

Plus: global search (Ctrl+K), per-person profile drawer w/ aliases, top neighbours, transactions, and citation evidence.

## Data

- 8000+ nodes / 7900+ edges / 600+ hyperedges
- Extracted from ~1000 daily diary chunks via v2.5 graphify prompt (101 batches × ~10 chunks)
- Author: 徐乃昌 (1869–1943), Qing-Republican bibliophile and philanthropist

## Local run

```bash
python build_views.py        # rebuild data/*.json from upstream batches
python -m http.server 8000   # serve
# open http://localhost:8000
```

`build_views.py` reads raw per-batch JSONs and emits 5 view files:
- `data/overview.json` — totals + breakdowns
- `data/transactions.json` — flattened TXN nodes with counterparties (walks edges + hyperedges)
- `data/people_graph.json` — PER↔PER edges, view-time dedup by canonical
- `data/locations.json` — Xu's visits + city resolution (venue → `位于` chain → known city)
- `data/people_profiles.json` — per-person detail for the profile drawer

## Stack

Vue 3 · Cytoscape.js · Tabulator · Leaflet (all CDN, no build step).

## Known issue: solar-date off-by-one in chunk filenames

The diary was written by lunar calendar (民国 convention). The OCR/chunking
pipeline (`chunk_entries.py`, upstream of this SPA) converted lunar dates to
solar (Gregorian) and used the solar date as the chunk filename. In a subset
of chunks the conversion is off by approximately one lunar year — e.g. a
chunk labeled `1920-02-04.md` whose frontmatter `lunar_date: 庚申年十二月廿七日`
should map to solar **1921-02-04**, not 1920-02-04.

### Current mitigation (browser-side, lossless)

`web/index.html` parses each chunk's `lunar_date` frontmatter on load using
`lunar-javascript` and computes the correct solar date. The map
`solarCorrection[origKey] → correctedSolar` is applied at display time via
`resolveSolar(iso)` and `fmtDate(iso)`. Affected dates render with a
`⚠ 阳历修正` badge in the reader header.

Chunk **keys** (filenames, JSON keys) are NOT mutated so existing graph IDs
keep working.

### Required full fix (post-graphify completion)

When all batch extractions finish, the canonical fix is:

1. Patch `chunk_entries.py` so lunar→solar uses an authoritative library
   (e.g. `lunar_python` in Python) instead of whatever heuristic produced
   the off-by-one.
2. Re-chunk: regenerate all `data/poc_200/YYYY-MM-DD.md` filenames with
   correct solar dates.
3. Re-run graphify v2.5 on the corrected chunks so all `source_location`
   fields on edges/txns/visits use correct solar.
4. Re-run `web/build_views.py`.
5. Remove `solarCorrection` / `resolveSolar` patch from FE — no longer needed.

Until then, treat **`lunar_date` as ground truth**; solar is derived.

## License

MIT for code. Diary content is public-domain historical material.
