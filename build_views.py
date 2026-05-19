"""
Aggregates raw per-batch JSONs from data/poc_200/graphify-out/ into per-view
JSON files in web/data/ for the static SPA. No merge_and_dedup needed.

Includes view-time dedup (canonical-keyed PER coalescing) without touching raw data.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── KNOWN-CITY COORDS ────────────────────────────────────────────────────────
# City canonical name → (lat, lon). Aliases handled via CITY_ALIAS below.
COORDS = {
    '上海': [31.230, 121.474], '南京': [32.060, 118.796], '苏州': [31.299, 120.585],
    '杭州': [30.274, 120.155], '北京': [39.904, 116.407], '南陵': [30.917, 118.335],
    '芜湖': [31.353, 118.433], '安庆': [30.531, 117.063], '镇江': [32.196, 119.456],
    '常州': [31.811, 119.974], '扬州': [32.394, 119.412], '无锡': [31.491, 120.312],
    '徐州': [34.205, 117.284], '蚌埠': [32.916, 117.389], '济南': [36.651, 117.000],
    '天津': [39.084, 117.201], '广州': [23.130, 113.264], '武汉': [30.593, 114.305],
    '长沙': [28.228, 112.939], '南昌': [28.682, 115.858], '福州': [26.075, 119.297],
    '嘉兴': [30.746, 120.755], '湖州': [30.894, 120.087], '绍兴': [30.030, 120.581],
    '宁波': [29.868, 121.544], '昆山': [31.385, 120.981], '太仓': [31.444, 121.107],
    '常熟': [31.654, 120.752], '青浦': [31.150, 121.124], '松江': [31.033, 121.222],
    '宝山': [31.405, 121.490], '崇明': [31.626, 121.397], '盐城': [33.349, 120.163],
    '阜阳': [32.890, 115.815], '六安': [31.752, 116.500], '泾县': [30.694, 118.412],
    '宣城': [30.940, 118.758], '广德': [30.893, 119.418], '合肥': [31.820, 117.227],
    '青岛': [36.067, 120.382], '烟台': [37.464, 121.448], '南翔': [31.299, 121.318],
    '南通': [31.980, 120.894], '九华山': [30.483, 117.804],
}

CITY_ALIAS = {
    '沪': '上海', '沪上': '上海', '徐家汇': '上海',
    '宁': '南京', '金陵': '南京',
    '苏': '苏州', '吴': '苏州',
    '杭': '杭州',
    '京': '北京', '京师': '北京', '北平': '北京',
    '宛陵': '南陵',
    '芜': '芜湖',
    '皖': '合肥', '皖南': '南陵',
    '汉口': '武汉',
    '九华': '九华山', '观音岩': '九华山',
    '狼山': '南通',
}

# ── HARDCODED VENUE → CITY ALIASES (民国 江南 well-known) ─────────────────────
# Used as last-resort fallback when `位于` chain doesn't reach a known city.
VENUE_ALIASES = {
    # Shanghai venues (酒楼/园林/娱乐场/慈善堂/古玩店)
    '都益处': '上海', '怡园': '苏州', '古香斋': '上海', '大世界': '上海',
    '仁济堂': '上海', '味古精舍': '上海', '一品香': '上海', '爱俪园': '上海',
    '小有天': '上海', '有余兴斋': '上海', '新世界': '上海', '大舞台': '上海',
    '共舞台': '上海', '半淞园': '上海', '邑庙': '上海', '邑庙内园': '上海',
    '同兴楼': '上海', '江湾': '上海', '功德林': '上海', '一枝香': '上海',
    '消闲别墅': '上海', '陶乐春': '上海', '新半斋': '上海', '惠中旅馆': '上海',
    '杏花楼': '上海', '六国饭店': '上海', '中央旅社': '上海', '中国饭店': '上海',
    '南京饭店': '上海', '梅龙镇': '上海', '徐园': '上海', '哈同花园': '上海',
    '商务印书馆': '上海', '中华书局': '上海', '佛经流通处': '上海',
    '俱乐部': '上海', '十号俱乐部': '上海', '出口公会': '上海',
    '兴华川菜馆': '上海', '丹桂第一台': '上海', '丹桂弟一台': '上海', '亦舞台': '上海',
    '先施乐园': '上海', '六三花园': '上海', '兆芳': '上海',
    '三新池': '上海', '中兴路': '上海', '广西路': '上海',
    '博古斋': '上海', '博远斋': '上海', '古物陈列所': '北京',
    '一江春': '上海',
    # Suzhou
    '城南别业': '苏州', '城南街': '苏州', '邵伯': '扬州',
    # Nantong (近代实业重镇)
    '大生': '南通', '大生纱厂': '南通',
    # Nanling / Anhui ancestral
    '遽园': '南陵', '内翰山': '南陵', '报本堂': '南陵',
    # Misc Jiangnan gardens
    '竞适园': '松江', '古逸园': '南翔', '葛氏园': '南翔',
    '北固甘露寺': '镇江', '净土庵': '镇江',
}


def normalize_source(sf):
    """Strip dir prefix from source_file. data/poc_200/X.md → X.md"""
    if not sf:
        return sf
    return Path(sf).name


# ── LOAD BATCHES ─────────────────────────────────────────────────────────────
batch_dir = ROOT / 'data' / 'poc_200' / 'graphify-out'
all_nodes, all_edges, all_hyper = [], [], []
seen_ids = set()
batch_files = sorted(batch_dir.glob('.graphify_v25_b10_*.json'))
for f in batch_files:
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'skip {f.name}: {e}')
        continue
    for n in d.get('nodes', []):
        if n.get('id') and n['id'] not in seen_ids:
            seen_ids.add(n['id'])
            all_nodes.append(n)
    all_edges.extend(d.get('edges', []))
    all_hyper.extend(d.get('hyperedges', []))

src = {'nodes': all_nodes, 'edges': all_edges, 'hyperedges': all_hyper}
print(f'aggregated {len(batch_files)} batches → {len(all_nodes)} nodes, {len(all_edges)} edges')

out_dir = Path(__file__).parent / 'data'
out_dir.mkdir(exist_ok=True)

nodes_by_id = {n['id']: n for n in src['nodes']}


# ── VIEW-TIME DEDUP (PER nodes by canonical) ─────────────────────────────────
# Build canonical_key → list of ids. Pick primary id (shortest id wins → cleanest).
# Build id → primary_id redirect map. Used for all view exports.
def per_canonical_key(n):
    md = n.get('metadata') or {}
    canonical = (md.get('canonical') or '').strip()
    label = (n.get('label') or '').strip()
    # Use canonical if it's a clean person name (no parenthesized role suffix).
    # Family members have canonical like "崇(徐乃昌之子)" — split on '(' to coalesce
    # 崇/崇儿/per_xu_chong all under key "崇".
    if canonical:
        base = re.split(r'[(（]', canonical)[0].strip()
        if base:
            return base
    return label or n['id']


canonical_to_ids = defaultdict(list)
for n in src['nodes']:
    if n.get('entity_type') == '人':
        canonical_to_ids[per_canonical_key(n)].append(n['id'])

per_redirect = {}  # any per id → primary id
for canon, ids in canonical_to_ids.items():
    # Prefer node whose label matches canonical (most "named"). Tiebreak: shortest id.
    def primary_score(i):
        n = nodes_by_id.get(i, {})
        label = n.get('label') or ''
        label_matches = 0 if label == canon else 1
        return (label_matches, len(i), i)
    primary = sorted(ids, key=primary_score)[0]
    for i in ids:
        per_redirect[i] = primary


def redirect(node_id):
    return per_redirect.get(node_id, node_id)


# ── 1) overview ──────────────────────────────────────────────────────────────
per_unique = len({per_redirect[i] for i in per_redirect})
entity_type_counts = Counter(n.get('entity_type', '?') for n in src['nodes'])
entity_type_counts_deduped = dict(entity_type_counts)
entity_type_counts_deduped['人 (dedup)'] = per_unique

overview = {
    'totals': {
        'nodes': len(src['nodes']),
        'nodes_deduped': len(src['nodes']) - len(per_redirect) + per_unique,
        'edges': len(src['edges']),
        'hyperedges': len(src.get('hyperedges', [])),
        'batches': len(batch_files),
    },
    'entity_types': entity_type_counts_deduped,
    'relation_types': dict(Counter(e.get('relation', '?') for e in src['edges'])),
    'date_range': None,
}
dates = sorted({n.get('captured_at', '') for n in src['nodes'] if n.get('captured_at', '').startswith('19')})
if dates:
    overview['date_range'] = [dates[0], dates[-1]]
(out_dir / 'overview.json').write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 2) transactions table ────────────────────────────────────────────────────
COUNTERPARTY_TYPES = {'人', '团体', '书籍'}
edges_by_node = defaultdict(list)
for e in src['edges']:
    edges_by_node[e.get('source')].append(('out', e))
    edges_by_node[e.get('target')].append(('in', e))
hyper_by_node = defaultdict(list)
for h in src['hyperedges']:
    for nid in h.get('nodes') or []:
        hyper_by_node[nid].append(h)

txns = []
for n in src['nodes']:
    if n.get('entity_type') != '交易':
        continue
    md = n.get('metadata') or {}
    counterparties = []
    seen_cp = set()
    for direction, e in edges_by_node.get(n['id'], []):
        other_id = e['target'] if direction == 'out' else e['source']
        other_n = nodes_by_id.get(other_id, {})
        if other_n.get('entity_type') not in COUNTERPARTY_TYPES:
            continue
        cp_id = redirect(other_id) if other_n.get('entity_type') == '人' else other_id
        if cp_id in seen_cp:
            continue
        seen_cp.add(cp_id)
        cp_n = nodes_by_id.get(cp_id, other_n)
        counterparties.append({
            'id': cp_id,
            'label': cp_n.get('label') or other_n.get('label'),
            'type': other_n.get('entity_type'),
            'relation': e.get('relation'),
        })
    for h in hyper_by_node.get(n['id'], []):
        for member_id in h.get('nodes') or []:
            if member_id == n['id']:
                continue
            mn = nodes_by_id.get(member_id, {})
            if mn.get('entity_type') not in COUNTERPARTY_TYPES:
                continue
            cp_id = redirect(member_id) if mn.get('entity_type') == '人' else member_id
            if cp_id in seen_cp:
                continue
            seen_cp.add(cp_id)
            cp_n = nodes_by_id.get(cp_id, mn)
            counterparties.append({
                'id': cp_id,
                'label': cp_n.get('label') or mn.get('label'),
                'type': mn.get('entity_type'),
                'relation': h.get('relation'),
            })
    txn_details = md.get('txn_details') or {}
    txns.append({
        'id': n['id'],
        'label': n.get('label'),
        'date': n.get('captured_at'),
        'source_file': normalize_source(n.get('source_file')),
        'evidence': (md.get('surface_forms') or [{}])[0].get('surface', n.get('label', '')),
        'people': counterparties,
        'amount': txn_details.get('amount'),
        'direction': txn_details.get('direction'),
    })
txns.sort(key=lambda t: t.get('date', '') or '')
(out_dir / 'transactions.json').write_text(json.dumps(txns, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 3) people_graph (人 + 人 relations) — DEDUPED ────────────────────────────
per_ids = {n['id'] for n in src['nodes'] if n.get('entity_type') == '人'}
# Merge aliases from all redirected ids into primary
primary_aliases = defaultdict(list)
primary_orig_ids = defaultdict(list)
primary_node_ref = {}
for n in src['nodes']:
    if n.get('entity_type') != '人':
        continue
    p = redirect(n['id'])
    primary_orig_ids[p].append(n['id'])
    md = n.get('metadata') or {}
    for sf in (md.get('surface_forms') or []):
        s = sf.get('surface')
        if s and s not in primary_aliases[p]:
            primary_aliases[p].append(s)
    if p == n['id']:
        primary_node_ref[p] = n

per_nodes_deduped = []
for pid, ref in primary_node_ref.items():
    md = ref.get('metadata') or {}
    per_nodes_deduped.append({
        'id': pid,
        'label': ref.get('label'),
        'canonical': md.get('canonical'),
        'aliases': primary_aliases[pid],
        'merged_ids': primary_orig_ids[pid],
        'degree': 0,
    })

# Edges with redirected endpoints, drop self-loops + dedup
per_edges_deduped = []
seen_edge_key = set()
for e in src['edges']:
    if e.get('source') not in per_ids or e.get('target') not in per_ids:
        continue
    s, t = redirect(e['source']), redirect(e['target'])
    if s == t:
        continue
    key = (s, t, e.get('relation'))
    if key in seen_edge_key:
        continue
    seen_edge_key.add(key)
    per_edges_deduped.append({
        'source': s, 'target': t,
        'relation': e.get('relation'),
        'confidence': e.get('confidence'),
        'evidence': (e.get('metadata') or {}).get('evidence_text'),
        'date': e.get('source_location'),
    })

deg = Counter()
for e in per_edges_deduped:
    deg[e['source']] += 1
    deg[e['target']] += 1
for n in per_nodes_deduped:
    n['degree'] = deg.get(n['id'], 0)

(out_dir / 'people_graph.json').write_text(
    json.dumps({'nodes': per_nodes_deduped, 'edges': per_edges_deduped}, ensure_ascii=False, indent=2),
    encoding='utf-8',
)


# ── 4) locations + 徐's visits ──────────────────────────────────────────────
xu_ids = {
    n['id'] for n in src['nodes']
    if n.get('entity_type') == '人' and (
        (n.get('metadata') or {}).get('canonical') == '徐乃昌'
        or (n.get('label') or '') == '徐乃昌'
    )
}
locs = {n['id']: n for n in src['nodes'] if n.get('entity_type') == '地'}

# Build location label → parent label map via `位于` (地→地)
parent_of = {}
for e in src['edges']:
    if e.get('relation') == '位于':
        s = nodes_by_id.get(e.get('source'), {})
        t = nodes_by_id.get(e.get('target'), {})
        if s.get('entity_type') == '地' and t.get('entity_type') == '地':
            parent_of.setdefault(s.get('label'), t.get('label'))


def to_canonical_city(name):
    if not name:
        return None
    if name in COORDS:
        return name
    if name in CITY_ALIAS:
        return CITY_ALIAS[name]
    if name in VENUE_ALIASES:
        c = VENUE_ALIASES[name]
        return CITY_ALIAS.get(c, c) if c in COORDS or c in CITY_ALIAS else None
    return None


def resolve_city(label, depth=4):
    """Chain `位于` up to a label resolvable via COORDS / CITY_ALIAS / VENUE_ALIASES."""
    direct = to_canonical_city(label)
    if direct:
        return direct
    seen = set()
    cur = label
    for _ in range(depth):
        if cur in seen:
            break
        seen.add(cur)
        nxt = parent_of.get(cur)
        if not nxt:
            break
        c = to_canonical_city(nxt)
        if c:
            return c
        cur = nxt
    return None


visits = []
for e in src['edges']:
    if e.get('source') in xu_ids and e.get('target') in locs and e.get('relation') in ('拜访', '位于'):
        loc_n = locs[e['target']]
        label = loc_n.get('label')
        visits.append({
            'date': e.get('source_location') or loc_n.get('captured_at'),
            'location_id': loc_n['id'],
            'location_label': label,
            'resolved_city': resolve_city(label),
            'evidence': (e.get('metadata') or {}).get('evidence_text'),
            'relation': e.get('relation'),
            'source_file': normalize_source(loc_n.get('source_file')),
        })
visits.sort(key=lambda v: v.get('date', '') or '')

mapped_cities = Counter(v['resolved_city'] for v in visits if v['resolved_city'])
unmapped = Counter(v['location_label'] for v in visits if not v['resolved_city'])

(out_dir / 'locations.json').write_text(json.dumps({
    'coords': COORDS,
    'locations': [{'id': k, 'label': v.get('label')} for k, v in locs.items()],
    'visits': visits,
    'xu_ids': sorted(xu_ids),
    'city_visit_counts': dict(mapped_cities.most_common()),
    'unmapped_top': dict(unmapped.most_common(40)),
}, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 5) per-person profile data (NEW — for entity-detail page) ────────────────
# For each PER primary id, gather: aliases, degree, top neighbours, txns, mentions
per_profile = {}
edges_by_per = defaultdict(list)
for e in per_edges_deduped:
    edges_by_per[e['source']].append(('out', e))
    edges_by_per[e['target']].append(('in', e))

txns_by_per = defaultdict(list)
for t in txns:
    for cp in t['people']:
        if cp.get('type') == '人':
            txns_by_per[cp['id']].append({
                'date': t['date'], 'label': t['label'], 'evidence': t['evidence'],
                'amount': t['amount'], 'direction': t['direction'], 'relation': cp.get('relation'),
            })

for n in per_nodes_deduped:
    pid = n['id']
    neighbours = Counter()
    rel_breakdown = Counter()
    sample_edges = []
    for direction, e in edges_by_per.get(pid, []):
        other = e['target'] if direction == 'out' else e['source']
        neighbours[other] += 1
        rel_breakdown[e['relation']] += 1
        if len(sample_edges) < 30:
            sample_edges.append({
                'other': other, 'direction': direction,
                'relation': e['relation'], 'evidence': e['evidence'], 'date': e['date'],
            })
    top_neighbours = []
    for nid, cnt in neighbours.most_common(20):
        nn = next((x for x in per_nodes_deduped if x['id'] == nid), None)
        if nn:
            top_neighbours.append({'id': nid, 'label': nn['label'], 'count': cnt})
    per_profile[pid] = {
        'id': pid,
        'label': n['label'],
        'canonical': n['canonical'],
        'aliases': n['aliases'],
        'merged_ids': n['merged_ids'],
        'degree': n['degree'],
        'relations': dict(rel_breakdown.most_common()),
        'top_neighbours': top_neighbours,
        'sample_edges': sample_edges,
        'txns': txns_by_per.get(pid, [])[:50],
    }

(out_dir / 'people_profiles.json').write_text(json.dumps(per_profile, ensure_ascii=False, indent=2), encoding='utf-8')


print(f'wrote {len(txns)} txns, {len(per_nodes_deduped)} people (was {len(per_ids)}), {len(visits)} visits')
print(f'mapped: {sum(mapped_cities.values())} / {len(visits)} → top cities: {list(mapped_cities.most_common(5))}')
print(f'unmapped venues remaining: {len(unmapped)}; top: {list(unmapped.most_common(5))}')
print(f'overview: {overview["totals"]}')
