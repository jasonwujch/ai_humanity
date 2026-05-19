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

## License

MIT for code. Diary content is public-domain historical material.
