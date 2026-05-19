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

## Known issues (defer until graphify rerun)

All these stem from the upstream extraction pipeline (`chunk_entries.py` +
graphify v2.5). FE has been patched where lossless mitigation is possible.
Full fix requires re-running graphify after the patches and is deferred
until all batches finish so we only re-extract once.

| # | Issue | FE mitigation | Real fix |
|---|---|---|---|
| 1 | Solar-date off-by-one (lunar→solar bug) | `resolveSolar` + ⚠ badge | Patch `chunk_entries.py` lunar lib, re-chunk, re-graphify |
| 2 | PER recall gaps — graphify misses some person names (e.g. 1923-03-06: 洪希甫, 李伯老, 李仲帅, 李伯耆 in plain text while 李少穆/汪禹丞/柏烈武/张仲昭 are caught) | None — visible only as unhighlighted names in reader | Re-prompt graphify with extra named-entity rules (esp. 老/帅/耆/伯-suffix elder honorifics); re-run extraction |
| 3 | Some venues unmapped on geo (~50 minor 上海 establishments) | Manual `VENUE_COORDS` additions in `build_views.py` | Crowd-source remaining coordinates |
| 4 | Some 拜访/位于 edges have wrong source (not Xu) which inflates 行迹 count | None | Tighten graphify prompt for these relations |
| 5 | Entity dedup gaps — same person extracted under multiple canonical strings. Symptoms: 字/号 not linked to 名 (e.g. 积余 = 徐乃昌 字, 寿老 = 余寿老); 同名异写 OCR variants (汪禹丞 vs 汪宇丞); 老/翁/丈/公 honorific suffixes treated as new entity (X翁 ≠ X). Existing view-time dedup uses canonical-name equality only. | None — visible as adjacent nodes that should be one in 人物关系 + 隐性关系 reveals some via co-occurrence | Stronger surface_forms 别名规则 in graphify v2.6 + biographical alias dict for top-N elite |

When the full graphify rerun is scheduled, walk this table top-to-bottom.

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
