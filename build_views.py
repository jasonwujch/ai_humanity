"""
Aggregates raw per-batch JSONs from data/poc_200/graphify-out/ into per-view
JSON files in web/data/ for the static SPA. No merge_and_dedup needed.

Includes view-time dedup (canonical-keyed PER coalescing) without touching raw data.

────────────────────────────────────────────────────────────────────────────
KNOWN-ISSUE: chunk solar-date off-by-one (see web/README.md for full notes)
────────────────────────────────────────────────────────────────────────────
The diary was written by lunar calendar. chunk_entries.py (upstream of this
script) converted lunar→solar incorrectly for some entries, so chunk filenames
and the `source_location` on edges/txns/visits can be off by ~1 lunar year.

Mitigation lives in the SPA (web/index.html):
  parseLunarString(chunks[date].lunar_date) → correct solar
  display via resolveSolar() / fmtDate(), badge as 阳历修正

Full fix requires: patch chunk_entries.py lunar→solar logic, re-chunk
all .md files, re-run graphify, re-run this script.
TODO once all graphify batches done.
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

# ── VENUE COORDINATES (1920s 上海 / 苏州 / etc. — well-known historical venues) ─
# Approximate (street-level for 福州路/南京路 cluster, neighborhood for parks).
VENUE_COORDS = {
    # 上海 — 福州路/四马路 (饮食娱乐古玩街)
    '都益处':[31.2340, 121.4824], '一品香':[31.2365, 121.4795], '一枝香':[31.2340, 121.4820],
    '小有天':[31.2342, 121.4820], '杏花楼':[31.2340, 121.4815], '陶乐春':[31.2342, 121.4823],
    '兴华川菜馆':[31.2342, 121.4825], '功德林':[31.2342, 121.4863], '新半斋':[31.2342, 121.4822],
    '同兴楼':[31.2342, 121.4823], '一江春':[31.2342, 121.4820],
    # 上海 — 戏院剧场
    '丹桂第一台':[31.2340, 121.4830], '丹桂弟一台':[31.2340, 121.4830],
    '亦舞台':[31.2340, 121.4830], '共舞台':[31.2340, 121.4810], '大舞台':[31.2340, 121.4830],
    '通俗剧场':[31.2326, 121.4760],
    # 上海 — 古玩书肆 (福州路东段)
    '古香斋':[31.2340, 121.4810], '博古斋':[31.2340, 121.4810], '博远斋':[31.2340, 121.4810],
    '来青阁':[31.2340, 121.4810], '佛经流通处':[31.2254, 121.4525],
    '商务印书馆':[31.2360, 121.4805], '中华书局':[31.2340, 121.4825],
    '忠厚书庄':[31.2340, 121.4810],
    # 上海 — 娱乐场 / 游园
    '大世界':[31.2320, 121.4750], '新世界':[31.2363, 121.4751], '先施乐园':[31.2360, 121.4774],
    '半淞园':[31.1960, 121.4905], '六三花园':[31.2340, 121.4810],
    # 上海 — 寺庙园林
    '爱俪园':[31.2253, 121.4520], '邑庙':[31.2243, 121.4925], '邑庙内园':[31.2243, 121.4925],
    '徐园':[31.2410, 121.4720],
    # 上海 — 慈善机构 / 团体
    '仁济堂':[31.2320, 121.4795], '出口公会':[31.2399, 121.4940],
    '十号俱乐部':[31.2340, 121.4820], '俱乐部':[31.2340, 121.4820],
    '兆芳':[31.2350, 121.4770],
    # 上海 — 街道
    '广西路':[31.2340, 121.4830], '中兴路':[31.2300, 121.4910], '三新池':[31.2340, 121.4830],
    '味古精舍':[31.2340, 121.4810], '消闲别墅':[31.2340, 121.4820],
    '惠中旅馆':[31.2360, 121.4790], '南京饭店':[31.2360, 121.4790],
    '六国饭店':[31.2360, 121.4790], '中央旅社':[31.2360, 121.4790],
    '中国饭店':[31.2360, 121.4790], '梅龙镇':[31.2330, 121.4760],
    # 上海 — 郊区
    '江湾':[31.2970, 121.4980], '徐家汇':[31.1930, 121.4370],
    # 苏州 — 园林古迹
    '怡园':[31.3105, 120.6190],
    # 镇江
    '北固甘露寺':[32.2169, 119.4533], '净土庵':[32.2070, 119.4400],
    # 松江 / 南翔 / 南通
    '竞适园':[31.0330, 121.2220], '古逸园':[31.2990, 121.3180], '葛氏园':[31.2990, 121.3180],
    '大生纱厂':[32.0150, 120.8550], '大生':[32.0150, 120.8550],
    # 南陵 (祖籍)
    '遽园':[30.9170, 118.3350], '内翰山':[30.9170, 118.3350], '报本堂':[30.9170, 118.3350],
    '城南别业':[31.3000, 120.5900], '城南街':[31.3000, 120.5900],
    # 苏州 — 名园 名街
    '拙政园':[31.3245, 120.6285], '留园':[31.3273, 120.5870], '网师园':[31.2965, 120.6315],
    '沧浪亭':[31.2975, 120.6230], '狮子林':[31.3245, 120.6310], '寒山寺':[31.3092, 120.5715],
    '虎丘':[31.3338, 120.5810], '观前街':[31.3145, 120.6228], '玄妙观':[31.3145, 120.6228],
    '木渎':[31.2735, 120.5215], '甪直':[31.2675, 120.7900],
    # 南京 — 名胜
    '玄武湖':[32.0772, 118.7975], '秦淮河':[32.0260, 118.7820], '夫子庙':[32.0260, 118.7820],
    '鸡鸣寺':[32.0680, 118.7960], '中山陵':[32.0594, 118.8480], '明孝陵':[32.0540, 118.8380],
    '紫金山':[32.0670, 118.8400], '莫愁湖':[32.0345, 118.7480],
    # 杭州 — 名胜
    '西湖':[30.2540, 120.1340], '灵隐寺':[30.2418, 120.0985], '岳庙':[30.2495, 120.1390],
    '断桥':[30.2570, 120.1450], '雷峰塔':[30.2310, 120.1485], '虎跑':[30.2070, 120.1325],
    '飞来峰':[30.2410, 120.0995], '六和塔':[30.1985, 120.1278], '九溪':[30.1990, 120.1180],
    # 镇江 — 名胜
    '金山寺':[32.2160, 119.4080], '焦山':[32.2378, 119.4798], '北固山':[32.2155, 119.4525],
    '甘露寺':[32.2160, 119.4530],
    # 扬州 — 名胜
    '瘦西湖':[32.4080, 119.4115], '大明寺':[32.4178, 119.4080], '平山堂':[32.4170, 119.4080],
    '何园':[32.3905, 119.4275], '个园':[32.4040, 119.4395],
    # 无锡 — 名胜
    '惠山':[31.5878, 120.2535], '寄畅园':[31.5872, 120.2530], '蠡园':[31.5170, 120.2640],
    '鼋头渚':[31.5145, 120.2225], '太湖':[31.2540, 120.0030],
    # 南通 — 名胜
    '濠河':[31.9820, 120.8975], '狼山':[32.0120, 120.8895], '军山':[32.0145, 120.8775],
    '剑山':[32.0240, 120.8845],
    # 嘉兴/湖州/绍兴/宁波
    '南湖':[30.7430, 120.7620], '烟雨楼':[30.7430, 120.7620],
    '太湖石':[30.8940, 120.0875], '飞英塔':[30.8930, 120.0888],
    '兰亭':[30.0035, 120.4940], '鉴湖':[30.0070, 120.5645], '禹陵':[29.9978, 120.6105],
    '天一阁':[29.8773, 121.5495], '阿育王寺':[29.8628, 121.7415], '天童寺':[29.8060, 121.7855],
    # 北京 — 名胜
    '颐和园':[39.9999, 116.2755], '圆明园':[40.0080, 116.2987], '紫禁城':[39.9163, 116.3972],
    '天坛':[39.8823, 116.4068], '故宫':[39.9163, 116.3972],
    '琉璃厂':[39.9018, 116.3902], '荣宝斋':[39.9019, 116.3895],
    # 武汉
    '黄鹤楼':[30.5460, 114.3045],
    # 苏州古玩书肆补充
    '古玩市场':[31.2340, 121.4810],
    '翰墨林':[31.2340, 121.4810],
    '新昌美术馆':[31.2340, 121.4810],
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
    '来青阁': '上海', '忠厚书庄': '上海', '蟬隐庐': '上海', '通俗剧场': '上海',
    '石竹山房': '上海', '味古精舍': '上海',
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

# ── Community detection (label propagation, pure-Python, weighted by edge count) ─
adj_for_lp = defaultdict(Counter)  # node → {neighbour: weight}
for e in per_edges_deduped:
    adj_for_lp[e['source']][e['target']] += 1
    adj_for_lp[e['target']][e['source']] += 1

# Initialize each node with its own community
labels = {n['id']: n['id'] for n in per_nodes_deduped}
import random as _rand
_rand.seed(0)
node_ids = [n['id'] for n in per_nodes_deduped]
for _iter in range(8):  # 8 passes empirically converges
    _rand.shuffle(node_ids)
    changed = 0
    for nid in node_ids:
        neighbours = adj_for_lp.get(nid)
        if not neighbours: continue
        # Vote by weighted neighbour labels
        votes = Counter()
        for nb, w in neighbours.items():
            votes[labels[nb]] += w
        if not votes: continue
        top_label = votes.most_common(1)[0][0]
        if labels[nid] != top_label:
            labels[nid] = top_label
            changed += 1
    if changed == 0: break

# Re-key labels to small integers, drop singletons
label_count = Counter(labels.values())
final_label_map = {}
next_id = 0
for lbl, cnt in label_count.most_common():
    if cnt >= 3:
        final_label_map[lbl] = next_id
        next_id += 1
for n in per_nodes_deduped:
    raw = labels[n['id']]
    n['community'] = final_label_map.get(raw, -1)
print(f'communities: {next_id} clusters of ≥3 PER, {sum(1 for n in per_nodes_deduped if n["community"]==-1)} singletons')

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

venues_by_city = defaultdict(list)
for v in visits:
    label = v['location_label']
    if label in VENUE_COORDS:
        city = v.get('resolved_city') or to_canonical_city(VENUE_ALIASES.get(label, '')) or '上海'
        venues_by_city[city].append(v)
# Aggregate venue dots: label → coord + counts
venue_dots = {}
for city, items in venues_by_city.items():
    bucket = defaultdict(list)
    for v in items:
        bucket[v['location_label']].append(v)
    venue_dots[city] = [
        {
            'label': lbl,
            'coord': VENUE_COORDS[lbl],
            'count': len(arr),
            'visits': arr[-6:],  # recent few
        }
        for lbl, arr in bucket.items()
    ]

(out_dir / 'locations.json').write_text(json.dumps({
    'coords': COORDS,
    'venue_coords': VENUE_COORDS,
    'venue_dots': venue_dots,
    'locations': [{'id': k, 'label': v.get('label')} for k, v in locs.items()],
    'visits': visits,
    'xu_ids': sorted(xu_ids),
    'city_visit_counts': dict(mapped_cities.most_common()),
    'unmapped_top': dict(unmapped.most_common(40)),
}, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 5) books ─────────────────────────────────────────────────────────────────
# Each book node: aliases, first/last seen, counterparties (people, orgs, txns)
books = []
for n in src['nodes']:
    if n.get('entity_type') != '书籍':
        continue
    md = n.get('metadata') or {}
    surface_forms = md.get('surface_forms') or []
    dates = sorted({sf.get('date') for sf in surface_forms if sf.get('date')})
    aliases = sorted({sf.get('surface') for sf in surface_forms if sf.get('surface')})
    # Walk direct edges
    people = []
    orgs = []
    txns_linked = []
    relations = Counter()
    for direction, e in edges_by_node.get(n['id'], []):
        other_id = e['target'] if direction == 'out' else e['source']
        other_n = nodes_by_id.get(other_id, {})
        ot = other_n.get('entity_type')
        rel = e.get('relation')
        relations[rel] += 1
        item = {
            'id': redirect(other_id) if ot == '人' else other_id,
            'label': nodes_by_id.get(redirect(other_id) if ot == '人' else other_id, other_n).get('label') or other_n.get('label'),
            'relation': rel,
            'date': e.get('source_location'),
            'evidence': (e.get('metadata') or {}).get('evidence_text'),
        }
        if ot == '人':
            people.append(item)
        elif ot == '团体':
            orgs.append(item)
        elif ot == '交易':
            txns_linked.append(item)
    # Hyperedge co-members
    for h in hyper_by_node.get(n['id'], []):
        for mid in h.get('nodes') or []:
            if mid == n['id']:
                continue
            mn = nodes_by_id.get(mid, {})
            if mn.get('entity_type') == '人':
                people.append({
                    'id': redirect(mid),
                    'label': nodes_by_id.get(redirect(mid), mn).get('label'),
                    'relation': h.get('relation'),
                    'date': None,
                    'evidence': h.get('label'),
                })
    books.append({
        'id': n['id'],
        'label': n.get('label'),
        'canonical': md.get('canonical'),
        'aliases': aliases,
        'first_seen': dates[0] if dates else None,
        'last_seen': dates[-1] if dates else None,
        'mentions': len(surface_forms),
        'people': people[:20],
        'orgs': orgs[:10],
        'txns': txns_linked[:20],
        'relation_counts': dict(relations.most_common()),
        'source_file': normalize_source(n.get('source_file')),
    })
books.sort(key=lambda b: -b['mentions'])
(out_dir / 'books.json').write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 6) per-person profile data ───────────────────────────────────────────────
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

# Pre-build alias timeline per primary id: walk all merged original nodes' surface_forms
alias_timeline_by_pid = defaultdict(list)
for n in src['nodes']:
    if n.get('entity_type') != '人':
        continue
    pid = redirect(n['id'])
    md = n.get('metadata') or {}
    for sf in (md.get('surface_forms') or []):
        if sf.get('date') and sf.get('surface'):
            alias_timeline_by_pid[pid].append({
                'date': sf.get('date'),
                'surface': sf.get('surface'),
                'rule': sf.get('rule'),
                'chunk_id': sf.get('chunk_id'),
                'confidence': sf.get('confidence'),
                'origin_id': n['id'],
            })
for pid in alias_timeline_by_pid:
    alias_timeline_by_pid[pid].sort(key=lambda x: (x['date'] or '', x['surface'] or ''))

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
    # Alias-by-surface summary: first/last/count
    alias_summary = defaultdict(lambda: {'first': None, 'last': None, 'count': 0, 'rule': None})
    for entry in alias_timeline_by_pid.get(pid, []):
        s = entry['surface']
        a = alias_summary[s]
        a['count'] += 1
        if a['first'] is None or entry['date'] < a['first']:
            a['first'] = entry['date']
            a['rule'] = entry['rule']
        if a['last'] is None or entry['date'] > a['last']:
            a['last'] = entry['date']
    alias_evolution = [{'surface': s, **info} for s, info in sorted(alias_summary.items(), key=lambda x: x[1]['first'] or '')]

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
        'alias_timeline': alias_timeline_by_pid.get(pid, [])[:200],  # cap for size
        'alias_evolution': alias_evolution,
    }

(out_dir / 'people_profiles.json').write_text(json.dumps(per_profile, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 7) misc entity profiles (疾病 / 灾害 / 官职 / 团体 / 地) ─────────────
misc_types = ('疾病', '灾害', '官职', '团体', '地')
misc_profiles = {}
for n in src['nodes']:
    et = n.get('entity_type')
    if et not in misc_types:
        continue
    md = n.get('metadata') or {}
    surface_forms = md.get('surface_forms') or []
    dates = sorted({sf.get('date') for sf in surface_forms if sf.get('date')})
    # Find people / events linked
    linked = []
    seen_l = set()
    for direction, e in edges_by_node.get(n['id'], []):
        other_id = e['target'] if direction == 'out' else e['source']
        other_n = nodes_by_id.get(other_id, {})
        ot = other_n.get('entity_type')
        if ot == '人':
            cid = redirect(other_id)
            cn = nodes_by_id.get(cid, other_n)
            key = cid
            if key in seen_l: continue
            seen_l.add(key)
            linked.append({'id': cid, 'label': cn.get('label'), 'type': '人', 'relation': e.get('relation'), 'date': e.get('source_location'), 'evidence': (e.get('metadata') or {}).get('evidence_text')})
    for h in hyper_by_node.get(n['id'], []):
        for mid in h.get('nodes') or []:
            if mid == n['id']: continue
            mn = nodes_by_id.get(mid, {})
            if mn.get('entity_type') == '人':
                cid = redirect(mid)
                cn = nodes_by_id.get(cid, mn)
                if cid in seen_l: continue
                seen_l.add(cid)
                linked.append({'id': cid, 'label': cn.get('label'), 'type': '人', 'relation': h.get('relation'), 'date': None, 'evidence': h.get('label')})
    misc_profiles[n['id']] = {
        'id': n['id'],
        'label': n.get('label'),
        'entity_type': et,
        'canonical': md.get('canonical'),
        'aliases': sorted({sf.get('surface') for sf in surface_forms if sf.get('surface')}),
        'mentions': len(surface_forms),
        'first_seen': dates[0] if dates else None,
        'last_seen': dates[-1] if dates else None,
        'linked_people': linked[:30],
    }
(out_dir / 'misc_entities.json').write_text(json.dumps(misc_profiles, ensure_ascii=False, indent=1), encoding='utf-8')


# ── 8) stats (precomputed aggregations) ─────────────────────────────────────
from collections import defaultdict as _dd
rel_per_month = _dd(lambda: _dd(int))   # month → relation → count
for e in src['edges']:
    d = (e.get('source_location') or '')
    if not d or len(d) < 7:
        continue
    m = d[:7]
    rel_per_month[m][e.get('relation') or '?'] += 1
for h in src['hyperedges']:
    label = h.get('label') or ''
    m_match = re.search(r'(19\d{2}-\d{2})', label)
    if not m_match:
        continue
    m = m_match.group(1)
    rel_per_month[m][h.get('relation') or '?'] += 1

person_per_month = _dd(lambda: _dd(int))  # person primary id → month → mentions
for n in src['nodes']:
    if n.get('entity_type') != '人':
        continue
    pid = redirect(n['id'])
    md = n.get('metadata') or {}
    for sf in (md.get('surface_forms') or []):
        d = sf.get('date') or sf.get('chunk_id') or ''
        if not d or len(d) < 7:
            continue
        person_per_month[pid][d[:7]] += 1

top_persons = sorted(person_per_month.keys(), key=lambda p: -sum(person_per_month[p].values()))[:20]
person_labels = {pid: nodes_by_id.get(pid, {}).get('label', pid) for pid in top_persons}

# Quality / reciprocity / confidence breakdown
conf_breakdown = Counter()
conf_by_rel = defaultdict(Counter)
score_buckets = Counter()
for e in src['edges']:
    c = e.get('confidence') or 'UNKNOWN'
    conf_breakdown[c] += 1
    conf_by_rel[e.get('relation') or '?'][c] += 1
    sc = e.get('confidence_score')
    if sc is None: score_buckets['none'] += 1
    elif sc >= 0.9: score_buckets['≥0.9'] += 1
    elif sc >= 0.7: score_buckets['0.7-0.9'] += 1
    elif sc >= 0.5: score_buckets['0.5-0.7'] += 1
    else: score_buckets['<0.5'] += 1

# Reciprocity: 赠↔受赠 and similar pairs
RECIPROCAL_PAIRS = [('赠', '受赠'), ('致书', '致书')]  # 致书 is one-way but we check return-书
recip_check = []
for forward, backward in RECIPROCAL_PAIRS:
    if forward == backward: continue
    forward_pairs = set()
    backward_pairs = set()
    for e in src['edges']:
        s = redirect(e['source']) if nodes_by_id.get(e['source'],{}).get('entity_type')=='人' else e['source']
        t = redirect(e['target']) if nodes_by_id.get(e['target'],{}).get('entity_type')=='人' else e['target']
        if e.get('relation') == forward:
            forward_pairs.add((s, t))
        elif e.get('relation') == backward:
            backward_pairs.add((t, s))  # flipped
    # Forward edges with no reciprocal entry
    missing = forward_pairs - backward_pairs
    extra = backward_pairs - forward_pairs
    recip_check.append({
        'forward': forward, 'backward': backward,
        'forward_total': len(forward_pairs),
        'backward_total': len(backward_pairs),
        'missing_reciprocal': len(missing),
        'samples': [{'src': s, 'src_label': nodes_by_id.get(s,{}).get('label'), 'tgt': t, 'tgt_label': nodes_by_id.get(t,{}).get('label')} for s, t in list(missing)[:10]],
    })

# Low-confidence sample (10 lowest)
low_conf_edges = sorted(
    [e for e in src['edges'] if e.get('confidence_score') is not None],
    key=lambda e: e.get('confidence_score', 0)
)[:20]
low_conf_sample = [
    {
        'source_label': nodes_by_id.get(e['source'],{}).get('label'),
        'target_label': nodes_by_id.get(e['target'],{}).get('label'),
        'relation': e.get('relation'),
        'score': e.get('confidence_score'),
        'evidence': (e.get('metadata') or {}).get('evidence_text'),
        'date': e.get('source_location'),
    }
    for e in low_conf_edges
]

# Anomaly: disappeared people (last mention old vs corpus end)
all_months = sorted(rel_per_month.keys())
corpus_end_month = all_months[-1] if all_months else None

# Compute last-month per primary PER from alias_timeline_by_pid
disappeared = []
for pid, entries in alias_timeline_by_pid.items():
    if not entries: continue
    last = max((e['date'] for e in entries), default='')
    total = len(entries)
    if total < 10:  # focus on prominent people only
        continue
    last_month = (last or '')[:7]
    if last_month and corpus_end_month and last_month < corpus_end_month:
        # Compute months gap
        try:
            y1, m1 = map(int, last_month.split('-'))
            y2, m2 = map(int, corpus_end_month.split('-'))
            gap = (y2 - y1) * 12 + (m2 - m1)
        except:
            gap = 0
        if gap >= 6:
            disappeared.append({
                'id': pid,
                'label': nodes_by_id.get(pid, {}).get('label'),
                'last_seen': last,
                'total_mentions': total,
                'months_absent': gap,
            })
disappeared.sort(key=lambda d: (-d['total_mentions'], -d['months_absent']))
disappeared = disappeared[:30]

# Spikes: per-relation z-score on monthly counts
import statistics
spikes = []
all_rels = set()
for d in rel_per_month.values(): all_rels.update(d.keys())
for rel in all_rels:
    series = [rel_per_month[m].get(rel, 0) for m in all_months]
    if len(series) < 4: continue
    mu = statistics.mean(series)
    sd = statistics.pstdev(series) or 1
    for m, v in zip(all_months, series):
        z = (v - mu) / sd
        if z >= 2.5:
            spikes.append({'month': m, 'relation': rel, 'count': v, 'mean': round(mu,1), 'zscore': round(z,2)})
spikes.sort(key=lambda x: -x['zscore'])
spikes = spikes[:20]

stats = {
    'months': sorted({m for m in rel_per_month.keys()}),
    'rel_per_month': {m: dict(d) for m, d in rel_per_month.items()},
    'top_persons': [{'id': p, 'label': person_labels[p], 'total': sum(person_per_month[p].values()), 'monthly': dict(person_per_month[p])} for p in top_persons],
    'confidence_breakdown': dict(conf_breakdown),
    'confidence_score_buckets': dict(score_buckets),
    'confidence_by_relation': {r: dict(d) for r, d in conf_by_rel.items()},
    'reciprocity': recip_check,
    'low_confidence_sample': low_conf_sample,
    'disappeared': disappeared,
    'spikes': spikes,
}
(out_dir / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 8) hyperedges (multi-party events) ──────────────────────────────────────
events_out = []
for h in src['hyperedges']:
    members = []
    for mid in h.get('nodes') or []:
        mn = nodes_by_id.get(mid, {})
        if not mn: continue
        cm_id = redirect(mid) if mn.get('entity_type') == '人' else mid
        cm_n = nodes_by_id.get(cm_id, mn)
        members.append({
            'id': cm_id,
            'label': cm_n.get('label') or mn.get('label'),
            'type': mn.get('entity_type'),
        })
    # Extract date from id or label
    date = None
    label = h.get('label') or ''
    import re as _re
    m = _re.search(r'(19\d{2}[-_]\d{2}[-_]\d{2})', h.get('id', '') + ' ' + label)
    if m:
        date = m.group(1).replace('_', '-')
    events_out.append({
        'id': h.get('id'),
        'label': label,
        'relation': h.get('relation'),
        'confidence': h.get('confidence'),
        'confidence_score': h.get('confidence_score'),
        'date': date,
        'source_file': normalize_source(h.get('source_file')),
        'members': members,
    })
events_out.sort(key=lambda e: e.get('date') or '')
(out_dir / 'events.json').write_text(json.dumps(events_out, ensure_ascii=False, indent=2), encoding='utf-8')

# ── 8) chunks (raw diary text + per-chunk entity index) ─────────────────────
chunk_dir = ROOT / 'data' / 'poc_200'
chunks = {}
for md_file in sorted(chunk_dir.glob('*.md')):
    text = md_file.read_text(encoding='utf-8')
    # Strip YAML frontmatter
    body = text
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            body = text[end+3:].lstrip('\n')
    # Strip leading # H1 line if any
    body_lines = body.split('\n')
    while body_lines and (not body_lines[0].strip() or body_lines[0].startswith('# ')):
        body_lines.pop(0)
    body = '\n'.join(body_lines).strip()
    # Parse frontmatter
    lunar = None; pdf = None; pages = None
    if text.startswith('---'):
        fm_end = text.find('---', 3)
        if fm_end != -1:
            fm = text[3:fm_end]
            for line in fm.split('\n'):
                line = line.strip()
                if line.startswith('lunar_date:'):
                    lunar = line.split(':', 1)[1].strip()
                elif line.startswith('source_pdf:'):
                    pdf = line.split(':', 1)[1].strip()
                elif line.startswith('source_pages:'):
                    raw = line.split(':', 1)[1].strip()
                    pages = raw.strip('[] ').replace(' ', '')
    date_key = md_file.stem  # YYYY-MM-DD
    chunks[date_key] = {'body': body, 'entities': [], 'lunar_date': lunar, 'source_pdf': pdf, 'source_pages': pages}

# Attach entities per chunk via surface_forms[].chunk_id (which equals the date key)
for n in src['nodes']:
    md = n.get('metadata') or {}
    et = n.get('entity_type')
    surface_forms = md.get('surface_forms') or []
    # Determine canonical id (redirect if PER)
    canonical_id = redirect(n['id']) if et == '人' else n['id']
    for sf in surface_forms:
        cid = sf.get('chunk_id')
        surface = sf.get('surface')
        if not cid or not surface or cid not in chunks:
            continue
        chunks[cid]['entities'].append({
            'id': canonical_id,
            'surface': surface,
            'label': n.get('label'),
            'type': et,
            'rule': sf.get('rule'),
        })

# Dedup entities per chunk by (surface, id)
for cid, ch in chunks.items():
    seen = set()
    uniq = []
    for ent in ch['entities']:
        k = (ent['surface'], ent['id'])
        if k in seen: continue
        seen.add(k)
        uniq.append(ent)
    ch['entities'] = uniq

# Drop empty chunks
chunks_out = {k: v for k, v in chunks.items() if v['body']}
(out_dir / 'chunks.json').write_text(json.dumps(chunks_out, ensure_ascii=False, indent=1), encoding='utf-8')

# ── 9c) kin (亲属) network ───────────────────────────────────────────────────
kin_edges_out = []
for e in src['edges']:
    if e.get('relation') != '亲属': continue
    s = e.get('source'); t = e.get('target')
    sn = nodes_by_id.get(s,{}); tn = nodes_by_id.get(t,{})
    if sn.get('entity_type') != '人' or tn.get('entity_type') != '人':
        continue
    md = e.get('metadata') or {}
    s_p = redirect(s); t_p = redirect(t)
    if s_p == t_p: continue
    kin_edges_out.append({
        'source': s_p, 'source_label': nodes_by_id.get(s_p,sn).get('label'),
        'target': t_p, 'target_label': nodes_by_id.get(t_p,tn).get('label'),
        'kin_type': md.get('kin_type'),
        'direction': md.get('direction'),
        'evidence': md.get('evidence_text'),
        'date': e.get('source_location'),
    })

(out_dir / 'kin.json').write_text(json.dumps(kin_edges_out, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'wrote {len(kin_edges_out)} kin edges')

# ── 10) co-occurrence matrix (implicit PER-PER relationships) ────────────────
from itertools import combinations
per_pair_count = Counter()
per_pair_dates = defaultdict(list)
for date, ch in chunks_out.items():
    per_ids_in_chunk = set()
    for ent in ch.get('entities', []):
        if ent.get('type') == '人':
            per_ids_in_chunk.add(ent['id'])
    if len(per_ids_in_chunk) < 2: continue
    for a, b in combinations(sorted(per_ids_in_chunk), 2):
        per_pair_count[(a,b)] += 1
        if len(per_pair_dates[(a,b)]) < 5:
            per_pair_dates[(a,b)].append(date)

# Set of existing PER edges (undirected) for subtraction
existing_per_edges = set()
for e in per_edges_deduped:
    s, t = sorted([e['source'], e['target']])
    existing_per_edges.add((s,t))

# Hidden pairs: high co-occurrence but no direct edge
hidden_pairs = []
for (a,b), cnt in per_pair_count.most_common():
    if cnt < 3: break
    if (a,b) in existing_per_edges: continue
    la = nodes_by_id.get(a,{}).get('label')
    lb = nodes_by_id.get(b,{}).get('label')
    hidden_pairs.append({
        'a': a, 'a_label': la, 'b': b, 'b_label': lb,
        'count': cnt, 'sample_dates': per_pair_dates[(a,b)],
    })
hidden_pairs = hidden_pairs[:200]

# Per-person hidden neighbours map (top 10 per primary)
hidden_by_person = defaultdict(list)
for hp in hidden_pairs:
    hidden_by_person[hp['a']].append({'id': hp['b'], 'label': hp['b_label'], 'count': hp['count'], 'dates': hp['sample_dates']})
    hidden_by_person[hp['b']].append({'id': hp['a'], 'label': hp['a_label'], 'count': hp['count'], 'dates': hp['sample_dates']})
for pid in hidden_by_person:
    hidden_by_person[pid].sort(key=lambda x: -x['count'])
    hidden_by_person[pid] = hidden_by_person[pid][:10]

(out_dir / 'cooccurrence.json').write_text(json.dumps({
    'hidden_pairs': hidden_pairs,
    'hidden_by_person': hidden_by_person,
}, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'wrote {len(hidden_pairs)} hidden co-occurrence pairs')

# ── 9) wiki pages (top-N PER + top-N books + top-N events) ───────────────────
wiki_dir = Path(__file__).parent / 'wiki'
wiki_dir.mkdir(exist_ok=True)

WIKI_CSS = '''
body{font-family:"Noto Serif SC","Songti SC","宋体",serif;background:#f5efe4;color:#1f1a14;margin:0;padding:20px;line-height:1.7}
.container{max-width:880px;margin:0 auto;background:#faf6ed;border:1px solid #d8cdb8;padding:36px 48px}
h1{font-size:28px;margin:0 0 8px;color:#9b2926;border-left:6px solid #9b2926;padding-left:14px}
h2{font-size:16px;color:#6b5d4c;margin-top:28px;padding-bottom:6px;border-bottom:1px solid #ece3d0;text-transform:uppercase;letter-spacing:.05em}
.meta{color:#6b5d4c;font-size:14px;margin-bottom:24px}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;margin:2px}
.chip-per{background:#dbeafe;color:#1f3f8a}
.chip-book{background:#ede9fe;color:#5f3b8a}
.chip-loc{background:#fed7aa;color:#a35c1a}
.chip-org{background:#dcfce7;color:#2c6e3e}
.chip-txn{background:#fce7f3;color:#a3296b}
.chip-evt{background:#cffafe;color:#0e6c75}
a{color:#9b2926;text-decoration:none}
a:hover{text-decoration:underline}
.row{padding:6px 0;border-bottom:1px solid #ece3d0;font-size:14px}
.dt{color:#6b5d4c;font-family:ui-monospace,monospace;font-size:12px;margin-right:8px}
.rel{color:#9b2926;font-weight:600}
nav{margin-bottom:18px}
nav a{margin-right:12px;color:#6b5d4c;font-size:13px}
.evidence{color:#3b3128;margin-top:4px}
'''

KIND_MAP = {'人':'per','地':'loc','团体':'org','书籍':'book','交易':'txn','事件':'evt'}

def kind_of(t):
    return KIND_MAP.get(t, 'per')

def esc(s):
    if not s: return ''
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def render_wiki_per(pid, profile):
    n = profile
    body = []
    body.append(f'<nav><a href="../index.html">← 返回总览</a><a href="../index.html#tab=people">人物关系图</a></nav>')
    body.append(f'<h1>{esc(n["label"])}</h1>')
    if n.get('canonical') and n['canonical'] != n['label']:
        body.append(f'<div class="meta">规范名: <strong>{esc(n["canonical"])}</strong></div>')
    if n.get('aliases'):
        body.append('<h2>别名</h2><div>' + ' '.join(f'<span class="chip">{esc(a)}</span>' for a in n['aliases']) + '</div>')
    body.append(f'<div class="meta">总度数 <strong>{n.get("degree","")}</strong></div>')
    if n.get('relations'):
        body.append('<h2>关系类型</h2><div>')
        for r, c in n['relations'].items():
            body.append(f'<span class="chip">{esc(r)} · {c}</span>')
        body.append('</div>')
    if n.get('top_neighbours'):
        body.append('<h2>主要关联人</h2><ul>')
        for nb in n['top_neighbours']:
            link = f'<a href="{nb["id"]}.html">{esc(nb["label"])}</a>' if isinstance(nb, dict) and nb.get('id') else esc(str(nb))
            body.append(f'<li>{link} · {nb.get("count","")} 次</li>')
        body.append('</ul>')
    if n.get('txns'):
        body.append('<h2>相关交易</h2>')
        for t in n['txns']:
            body.append(f'<div class="row"><span class="dt">{esc(t.get("date"))}</span><span class="rel">{esc(t.get("relation",""))}</span> {esc(t.get("label",""))}<div class="evidence">{esc(t.get("evidence",""))}</div></div>')
    if n.get('sample_edges'):
        body.append('<h2>关系证据</h2>')
        for e in n['sample_edges'][:30]:
            body.append(f'<div class="row"><span class="dt">{esc(e.get("date"))}</span><span class="rel">{esc(e.get("relation",""))}</span> <a href="{esc(e.get("other"))}.html">{esc(e.get("other"))}</a><div class="evidence">{esc(e.get("evidence",""))}</div></div>')
    if n.get('merged_ids') and len(n['merged_ids']) > 1:
        body.append('<h2>合并 ID</h2><div>' + ' '.join(f'<code style="font-family:ui-monospace,monospace;font-size:11px;color:#6b5d4c">{esc(mid)}</code>' for mid in n['merged_ids']) + '</div>')
    return f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{esc(n["label"])} - 徐乃昌日记 KG</title><style>{WIKI_CSS}</style></head><body><div class="container">{"".join(body)}</div></body></html>'

# Generate top-100 PER pages
top_per_ids = sorted(per_profile.keys(), key=lambda i: -per_profile[i].get('degree', 0))[:100]
for pid in top_per_ids:
    pr = per_profile[pid]
    (wiki_dir / f'{pid}.html').write_text(render_wiki_per(pid, pr), encoding='utf-8')

# Wiki index
idx_lines = [f'<nav><a href="../index.html">← 返回总览</a></nav>', '<h1>实体 Wiki 索引</h1>', f'<div class="meta">收录 top {len(top_per_ids)} 人物</div>', '<ul>']
for pid in top_per_ids:
    pr = per_profile[pid]
    idx_lines.append(f'<li><a href="{pid}.html">{esc(pr["label"])}</a> · {pr.get("degree","")} 度</li>')
idx_lines.append('</ul>')
(wiki_dir / 'index.html').write_text(f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>实体 Wiki · 徐乃昌日记 KG</title><style>{WIKI_CSS}</style></head><body><div class="container">{"".join(idx_lines)}</div></body></html>', encoding='utf-8')

print(f'wrote {len(top_per_ids)} wiki pages + index')

# ── 9b) thematic special pages ───────────────────────────────────────────────
specials_dir = Path(__file__).parent / 'specials'
specials_dir.mkdir(exist_ok=True)

SPECIAL_CSS = WIKI_CSS  # reuse

def render_special(title, lede, sections):
    body = [f'<nav><a href="../index.html">← 返回总览</a><a href="../wiki/index.html">实体 Wiki</a></nav>']
    body.append(f'<h1>{esc(title)}</h1>')
    body.append(f'<div class="meta">{esc(lede)}</div>')
    for s in sections:
        body.append(f'<h2>{esc(s["title"])}</h2>')
        if s.get('intro'):
            body.append(f'<div style="color:#3b3128;margin-bottom:12px">{s["intro"]}</div>')
        if s.get('items'):
            body.append('<div>')
            for item in s['items']:
                body.append(f'<div class="row">{item}</div>')
            body.append('</div>')
    return f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{esc(title)} - 徐乃昌日记 KG</title><style>{SPECIAL_CSS}</style></head><body><div class="container">{"".join(body)}</div></body></html>'

# Topic 1: 1921 皖北赈灾
disasters_anhui_1921 = []
for n in src['nodes']:
    if n.get('entity_type') != '灾害': continue
    md = n.get('metadata') or {}
    sfs = md.get('surface_forms') or []
    dates = [sf.get('date') for sf in sfs if sf.get('date') and sf.get('date','').startswith('1921')]
    label = n.get('label','')
    if dates and ('皖' in label or '安徽' in label or '凤' in label or '阜' in label or '霍' in label or '南陵' in label):
        disasters_anhui_1921.append({'label': label, 'dates': dates, 'id': n['id']})

# Related 团体 (赈灾) and txns
relief_orgs = []
for n in src['nodes']:
    if n.get('entity_type') != '团体': continue
    label = n.get('label','')
    if '振' in label or '赈' in label or '振灾' in label or '义振' in label or '极贫会' in label:
        relief_orgs.append({'id': n['id'], 'label': label})

# Resource: 资助 txns
zizhu_txns = [t for t in txns if any('资助' in (p.get('relation','') or '') for p in t.get('people',[]))]
zizhu_1921 = [t for t in zizhu_txns if (t.get('date','') or '').startswith('1921')]

s1_items = []
for d in sorted(disasters_anhui_1921, key=lambda x: x['dates'][0]):
    s1_items.append(f'<span class="dt">{d["dates"][0]}</span> <strong>{esc(d["label"])}</strong>')
s2_items = []
for org in relief_orgs[:20]:
    s2_items.append(f'<strong>{esc(org["label"])}</strong>')
s3_items = []
for t in zizhu_1921[:30]:
    people_str = '、'.join(p.get('label','') for p in (t.get('people') or [])[:4])
    s3_items.append(f'<span class="dt">{esc(t.get("date",""))}</span> <strong>{esc(t.get("label",""))}</strong> · {esc(people_str)} <div class="evidence">{esc(t.get("evidence",""))}</div>')

special1_html = render_special(
    '1921 皖北赈灾',
    '1921 年安徽北部连续遭遇水患，徐乃昌作为同乡士绅与多家慈善机构合作筹办赈务。本页汇总该年灾害条目、相关赈灾机构、与该年资助类交易。',
    [
        {'title': f'1921 年安徽灾害条目 ({len(disasters_anhui_1921)})', 'items': s1_items},
        {'title': f'相关赈灾机构 / 慈善团体 ({len(relief_orgs)})', 'items': s2_items},
        {'title': f'1921 年资助交易 ({len(zizhu_1921)})', 'items': s3_items},
    ]
)
(specials_dir / 'wanbei-1921.html').write_text(special1_html, encoding='utf-8')

# Topic 2: 戏楼社交
DRAMA_VENUES = {'共舞台', '丹桂第一台', '大舞台', '亦舞台', '丹桂弟一台', '通俗剧场'}
DRAMA_RELATED = {'同席'}
drama_events = [h for h in src['hyperedges'] if any(d in (h.get('label') or '') for d in DRAMA_VENUES)]
drama_events_by_venue = defaultdict(list)
for h in drama_events:
    for v in DRAMA_VENUES:
        if v in (h.get('label') or ''):
            drama_events_by_venue[v].append(h)

s_drama_sections = []
for venue, events in drama_events_by_venue.items():
    items = []
    for h in events:
        members = []
        for mid in (h.get('nodes') or []):
            mn = nodes_by_id.get(mid, {})
            if mn.get('entity_type') == '人':
                pid = redirect(mid)
                pname = nodes_by_id.get(pid, mn).get('label')
                members.append(f'<span class="chip chip-per">{esc(pname)}</span>')
        items.append(f'<span class="dt">{esc(h.get("label",""))}</span> {"".join(members)}')
    s_drama_sections.append({'title': f'{venue} ({len(events)} 次同席)', 'items': items})

if not s_drama_sections:
    s_drama_sections = [{'title': '无数据', 'items': []}]

special2_html = render_special(
    '戏楼社交',
    '民国上海 福州路 戏院云集，徐乃昌日记中多次记录戏园应酬。本页按戏楼分组列出同席事件与参与人。',
    s_drama_sections
)
(specials_dir / 'drama-shanghai.html').write_text(special2_html, encoding='utf-8')

# Topic 3: 全部灾害 (all disasters with timeline)
all_disasters = []
for n in src['nodes']:
    if n.get('entity_type') != '灾害': continue
    md = n.get('metadata') or {}
    sfs = md.get('surface_forms') or []
    dates = sorted({sf.get('date') for sf in sfs if sf.get('date')})
    all_disasters.append({'id': n['id'], 'label': n.get('label'), 'dates': dates})
all_disasters.sort(key=lambda x: x['dates'][0] if x['dates'] else '')
s3_items = [f'<span class="dt">{esc(d["dates"][0] if d["dates"] else "?")}</span> <strong>{esc(d["label"])}</strong>' for d in all_disasters]

special3_html = render_special(
    '灾害编年',
    f'日记中提及的全部 {len(all_disasters)} 条灾害条目按时间排列。涵盖水灾、旱灾、兵灾、地震、火警等。',
    [{'title': f'灾害条目 ({len(all_disasters)})', 'items': s3_items}]
)
(specials_dir / 'disasters-all.html').write_text(special3_html, encoding='utf-8')

# Topic 4: 藏书购入流水 (books w/ 商务/赠/受赠/资助 txns)
book_txns = []
for t in txns:
    book_cps = [p for p in (t.get('people') or []) if p.get('type') == '书籍']
    if book_cps:
        book_txns.append((t, book_cps))
book_txns.sort(key=lambda x: x[0].get('date',''))
s4_items = []
for t, bks in book_txns[:200]:
    bk_chips = ' '.join(f'<span class="chip chip-book">{esc(b["label"])}</span>' for b in bks)
    people_chips = ' '.join(f'<span class="chip chip-per">{esc(p["label"])}</span>' for p in t.get('people',[]) if p.get('type')=='人')
    s4_items.append(f'<span class="dt">{esc(t.get("date",""))}</span> {bk_chips} {people_chips} <div class="evidence">{esc(t.get("evidence",""))}</div>')

special4_html = render_special(
    '藏书购入流水',
    f'日记中涉及书籍的交易、赠予、受赠记录共 {len(book_txns)} 条。徐乃昌是著名藏书家，本页是其藏书来源最直接的一手记录。',
    [{'title': f'书籍-交易流水 (前 200 / {len(book_txns)})', 'items': s4_items}]
)
(specials_dir / 'book-acquisitions.html').write_text(special4_html, encoding='utf-8')

# Topic 5: 致书往来 (top 致书 pairs)
zhi_shu_pairs = Counter()
zhi_shu_evidence = {}
for e in src['edges']:
    if e.get('relation') != '致书': continue
    s, t_id = e.get('source'), e.get('target')
    sn, tn = nodes_by_id.get(s,{}), nodes_by_id.get(t_id,{})
    if sn.get('entity_type') != '人' or tn.get('entity_type') != '人': continue
    sp = redirect(s); tp = redirect(t_id)
    if sp == tp: continue
    pair_key = (sp, tp)
    zhi_shu_pairs[pair_key] += 1
    if pair_key not in zhi_shu_evidence:
        zhi_shu_evidence[pair_key] = []
    if len(zhi_shu_evidence[pair_key]) < 3:
        zhi_shu_evidence[pair_key].append({
            'date': e.get('source_location'),
            'evidence': (e.get('metadata') or {}).get('evidence_text'),
        })

s5_items = []
for (a, b), cnt in zhi_shu_pairs.most_common(60):
    la = nodes_by_id.get(a,{}).get('label')
    lb = nodes_by_id.get(b,{}).get('label')
    ev_lines = ''.join(f'<div style="font-size:11px;color:#6b5d4c;margin-top:2px">{esc(e["date"])} · {esc(e["evidence"] or "")}</div>' for e in zhi_shu_evidence.get((a,b), []))
    s5_items.append(f'<strong>{esc(la)}</strong> → <strong>{esc(lb)}</strong> · <span class="rel">{cnt} 通</span>{ev_lines}')

special5_html = render_special(
    '致书往来',
    f'按致书次数排名的人物对。共 {len(zhi_shu_pairs)} 对收发关系，前 60 显示在此。揭示徐乃昌日常通信网络的核心。',
    [{'title': f'Top 60 致书往来对', 'items': s5_items}]
)
(specials_dir / 'correspondence.html').write_text(special5_html, encoding='utf-8')

# Topic 6: 治病记录 (疾病 + 治病 edges)
illness_records = []
for n in src['nodes']:
    if n.get('entity_type') != '疾病': continue
    md = n.get('metadata') or {}
    sfs = md.get('surface_forms') or []
    dates = sorted({sf.get('date') for sf in sfs if sf.get('date')})
    # Find 治病 edges touching this illness
    healers = []
    for direction, e in edges_by_node.get(n['id'], []):
        if e.get('relation') == '治病':
            other_id = e['target'] if direction == 'out' else e['source']
            other_n = nodes_by_id.get(other_id, {})
            if other_n.get('entity_type') == '人':
                healers.append({
                    'id': redirect(other_id),
                    'label': nodes_by_id.get(redirect(other_id), other_n).get('label'),
                    'date': e.get('source_location'),
                    'evidence': (e.get('metadata') or {}).get('evidence_text'),
                })
    illness_records.append({
        'label': n.get('label'), 'dates': dates, 'healers': healers,
    })
illness_records.sort(key=lambda x: x['dates'][0] if x['dates'] else '')
s6_items = []
for ir in illness_records:
    healer_str = ', '.join(f'<span class="chip chip-per">{esc(h["label"])}</span>' for h in ir['healers'][:6])
    s6_items.append(f'<span class="dt">{esc(ir["dates"][0] if ir["dates"] else "?")}</span> <strong>{esc(ir["label"])}</strong> {healer_str}')

special6_html = render_special(
    '治病记录',
    f'日记中提及的 {len(illness_records)} 例疾病条目及对应的医者关系。',
    [{'title': '疾病条目 + 治病者', 'items': s6_items}]
)
(specials_dir / 'medical.html').write_text(special6_html, encoding='utf-8')

# Topic 7: 同席聚会全集
all_tongxi = [h for h in src['hyperedges'] if h.get('relation') == '同席']
s7_items = []
for h in sorted(all_tongxi, key=lambda x: x.get('label',''))[:120]:
    members = []
    for mid in (h.get('nodes') or []):
        mn = nodes_by_id.get(mid, {})
        if mn.get('entity_type') == '人':
            pid = redirect(mid)
            pname = nodes_by_id.get(pid, mn).get('label')
            members.append(f'<span class="chip chip-per">{esc(pname)}</span>')
    s7_items.append(f'<span class="dt">{esc(h.get("label",""))}</span> {" ".join(members)}')

special7_html = render_special(
    '同席聚会全集',
    f'共记 {len(all_tongxi)} 次同席事件 (多人聚会), 前 120 显示。揭示徐乃昌的实际社交规模。',
    [{'title': f'同席事件 (前 120 / {len(all_tongxi)})', 'items': s7_items}]
)
(specials_dir / 'gatherings.html').write_text(special7_html, encoding='utf-8')

# Topic 8: 安徽同乡圈
anhui_keywords = ['皖', '安徽', '南陵', '芜湖', '宣城', '泾县', '广德', '阜阳', '六安']
anhui_persons = []
for n in src['nodes']:
    if n.get('entity_type') != '人': continue
    md = n.get('metadata') or {}
    canonical = md.get('canonical') or ''
    # Heuristic: person canonical contains 安徽 county OR linked to 安徽 locations
    if any(kw in canonical for kw in anhui_keywords):
        if redirect(n['id']) == n['id']:
            anhui_persons.append({'id': n['id'], 'label': n.get('label'), 'canonical': canonical})
s8_items = [f'<strong>{esc(p["label"])}</strong> <span style="color:#888;font-size:11px">{esc(p["canonical"])}</span>' for p in anhui_persons]

special8_html = render_special(
    '安徽同乡圈',
    f'徐乃昌祖籍南陵，日记中提及的 {len(anhui_persons)} 位与安徽相关人物 (canonical 含皖/安徽/县名)。',
    [{'title': '安徽相关人物', 'items': s8_items}]
)
(specials_dir / 'anhui-network.html').write_text(special8_html, encoding='utf-8')

# Index
specials_idx = [
    f'<nav><a href="../index.html">← 返回总览</a></nav>',
    '<h1>专题策展</h1>',
    '<div class="meta">数据驱动的主题页：从分散日记条目里按议题聚合。点击主题进入。</div>',
    '<ul>',
    '<li><a href="wanbei-1921.html"><strong>1921 皖北赈灾</strong></a> — 灾害+赈务机构+资助流水</li>',
    '<li><a href="disasters-all.html"><strong>灾害编年</strong></a> — 全部灾害条目时间线</li>',
    '<li><a href="book-acquisitions.html"><strong>藏书购入流水</strong></a> — 涉书的赠/受赠/购置交易</li>',
    '<li><a href="correspondence.html"><strong>致书往来</strong></a> — top 60 通信对</li>',
    '<li><a href="medical.html"><strong>治病记录</strong></a> — 疾病条目 + 医者</li>',
    '<li><a href="gatherings.html"><strong>同席聚会全集</strong></a> — 多人聚会 hyperedges</li>',
    '<li><a href="drama-shanghai.html"><strong>戏楼社交</strong></a> — 福州路戏院同席</li>',
    '<li><a href="anhui-network.html"><strong>安徽同乡圈</strong></a> — 皖籍人物清单</li>',
    '</ul>',
]
(specials_dir / 'index.html').write_text(
    f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>专题策展 · 徐乃昌日记 KG</title><style>{SPECIAL_CSS}</style></head><body><div class="container">{"".join(specials_idx)}</div></body></html>',
    encoding='utf-8',
)
print(f'wrote 2 specials: wanbei-1921 ({len(disasters_anhui_1921)} disasters), drama-shanghai ({len(drama_events)} events)')
print(f'wrote {len(chunks_out)} chunks (raw text + entity highlights)')
print(f'wrote {len(txns)} txns, {len(per_nodes_deduped)} people (was {len(per_ids)}), {len(visits)} visits')
print(f'mapped: {sum(mapped_cities.values())} / {len(visits)} → top cities: {list(mapped_cities.most_common(5))}')
print(f'unmapped venues remaining: {len(unmapped)}; top: {list(unmapped.most_common(5))}')
print(f'overview: {overview["totals"]}')
