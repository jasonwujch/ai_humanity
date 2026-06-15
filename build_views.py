"""
Aggregates raw per-batch JSONs from data/poc_200/graphify-out/ into per-view
JSON files in web/data/ for the static SPA. No merge_and_dedup needed.

Includes view-time dedup (canonical-keyed PER coalescing) without touching raw data.

────────────────────────────────────────────────────────────────────────────
CALENDAR: off-by-one-year FIXED at source 2026-05-28 (see fix_calendar.py).
chunk_entries.py converter patched; 507 off-by-year entries corrected across
md / chunks / graph batches. So captured_at / source_location are now correct.
The SPA's parseLunarString→resolveSolar mitigation is now redundant (harmless;
it re-derives the same correct solar date). Safe to remove later.
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
    # 上海 — 福州路书肆/古玩/菜馆 (E2: top unmapped venues)
    '聚丰园':[31.2342, 121.4822], '中国书店':[31.2340, 121.4815], '鸿宝斋':[31.2340, 121.4812],
    '大东书局':[31.2342, 121.4815], '锦文堂':[31.2340, 121.4812], '汉文渊':[31.2340, 121.4812],
    '九华堂':[31.2340, 121.4815], '博雅斋':[31.2340, 121.4812], '新昌美术馆':[31.2340, 121.4815],
    '大东酒楼':[31.2342, 121.4815], '晋隆西餐':[31.2342, 121.4820], '福州路':[31.2340, 121.4840],
    # 上海 — 城隍庙/南市市场
    '邑庙市场':[31.2243, 121.4925], '古玩市场':[31.2243, 121.4925], '蓬莱市场':[31.2150, 121.4900],
    '文庙公园':[31.2160, 121.4830],
    # 上海 — 戏院 / 旅社
    '新光戏院':[31.2370, 121.4830], '新光大戏院':[31.2370, 121.4830], '北京大戏院':[31.2333, 121.4790],
    '北京戏院':[31.2333, 121.4790], '中央戏院':[31.2333, 121.4810], '金城戏院':[31.2400, 121.4800],
    '南京大戏院':[31.2320, 121.4810], '大光明戏院':[31.2310, 121.4560], '新中央':[31.2330, 121.4790],
    '大东旅社':[31.2360, 121.4790], '老惠中旅馆':[31.2360, 121.4790],
    # 上海 — 园林寺庙
    '法国公园':[31.2160, 121.4670], '兆丰花园':[31.2200, 121.4200], '兆丰公园':[31.2200, 121.4200],
    '玉佛寺':[31.2460, 121.4450], '觉园':[31.2200, 121.4600],
    # 苏州 / 杭州 / 北京 landmarks
    '留园':[31.3250, 120.5970], '虎邱':[31.3470, 120.5730], '西泠印社':[30.2550, 120.1440],
    '报国寺':[39.8862, 116.3550],
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
batch_files = sorted(batch_dir.glob('.graphify_v25_*.json'))  # b10_ + b5_ retries + b20_ legacy
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

# Drop dangling edges/hyperedge-members whose endpoint was never defined as a node
# (a subagent emitted an edge to an id it never produced). Views filter these at lookup
# via nodes_by_id.get(id, {}), but counts would otherwise overstate the graph.
_node_id_set = {n['id'] for n in all_nodes}
_kept_edges = [e for e in all_edges if e.get('source') in _node_id_set and e.get('target') in _node_id_set]
_dropped_edges = len(all_edges) - len(_kept_edges)
_kept_hyper = []
_dropped_hmembers = 0
for h in all_hyper:
    members = [m for m in h.get('nodes', []) if m in _node_id_set]
    _dropped_hmembers += len(h.get('nodes', [])) - len(members)
    if len(members) >= 2:
        h2 = dict(h); h2['nodes'] = members; _kept_hyper.append(h2)
all_edges, all_hyper = _kept_edges, _kept_hyper

src = {'nodes': all_nodes, 'edges': all_edges, 'hyperedges': all_hyper}
print(f'aggregated {len(batch_files)} batches → {len(all_nodes)} nodes, {len(all_edges)} edges '
      f'(dropped {_dropped_edges} dangling edges, {_dropped_hmembers} dangling hyper-members)')

out_dir = Path(__file__).parent / 'data'
out_dir.mkdir(exist_ok=True)

nodes_by_id = {n['id']: n for n in src['nodes']}

# ── date → 原书页码 / pdf ──────────────────────────────────────────────────────
# DEBUG (图谱改进0615 "systematically fix 页码"): the 影印《徐乃昌日记》is paginated
# CONTINUOUSLY across the whole book (~1→1819). The OCR was split into 19 PDF parts, each
# STARTING at an arbitrary printed page (上半部→1, 4第一部分→1380, 4第六部分→1740; the 补漏/
# 遗漏 supplements are NON-contiguous — pages gathered from scattered book locations). So
# frontmatter `source_pages` is the PART-LOCAL pdf page index, NOT the 原书页码 — and no
# single per-part offset works for the supplements. dots.ocr captured the true printed
# number in each verso header ("N 徐乃昌日记"); build_page_map.py extracts those per page and
# interpolates the rest → data/page_map.json {part:{pdf_idx:原书页码}}. page_for() just looks
# it up (per-page, no offset assumptions). Verified anchors 1920-03-12→6, 1920-08-13→58.
# Regenerate when raw_ocr changes:  python build_page_map.py
date_to_meta = {}
_poc_dir = ROOT / 'data' / 'poc_200'
_re_pages = re.compile(r'^source_pages:\s*(.+)$', re.M)
_re_pdf = re.compile(r'^source_pdf:\s*(.+)$', re.M)


def _parse_pagespan(s):
    """'[220, 221]' / '183, 183' → (220, 221) pdf-index ints, or (None, None)."""
    nums = re.findall(r'\d+', s or '')
    if not nums:
        return (None, None)
    return (int(nums[0]), int(nums[-1]))


for _mf in _poc_dir.glob('*.md'):
    if _mf.stem.startswith('_'):
        continue
    _t = _mf.read_text(encoding='utf-8')[:400]
    mp = _re_pages.search(_t); mpdf = _re_pdf.search(_t)
    _pdf = mpdf.group(1).strip() if mpdf else None
    _lo, _hi = _parse_pagespan(mp.group(1) if mp else '')
    date_to_meta[_mf.stem] = {'pdf': _pdf, 'p_lo': _lo, 'p_hi': _hi}

# per-page 原书页码 map built from OCR verso headers (build_page_map.py)
_PAGE_MAP = {}
_page_map_file = ROOT / 'data' / 'page_map.json'
if _page_map_file.exists():
    _PAGE_MAP = json.loads(_page_map_file.read_text(encoding='utf-8'))
else:
    print('  ⚠ data/page_map.json missing — run `python build_page_map.py`; 页码 will be blank')


def _printed_page(pdf, idx):
    """part-local pdf index → 原书页码 via page_map. part key is the dir name (no .pdf)."""
    if idx is None or not pdf:
        return None
    part = _PAGE_MAP.get(pdf) or _PAGE_MAP.get(pdf.replace('.pdf', ''))
    return part.get(str(idx)) if part else None


def page_for(date):
    """原书页码 (printed-book page, from OCR-header map). 'lo' or 'lo-hi' string, or None."""
    m = date_to_meta.get(date or '')
    if not m or m.get('p_lo') is None:
        return None
    lo = _printed_page(m['pdf'], m['p_lo'])
    hi = _printed_page(m['pdf'], m['p_hi'] if m['p_hi'] is not None else m['p_lo'])
    if lo is None:
        return None
    if hi is None or hi == lo:
        return f'{lo}'
    return f'{lo}-{hi}'


print(f'  原书页码: page_map loaded ({sum(len(v) for v in _PAGE_MAP.values())} pages, '
      f'{len(_PAGE_MAP)} parts) — continuous pagination from OCR headers')


# 性质 (income/expense) lexicon — derive from txn label/evidence verbs.
INCOME_KW = ('售', '收', '汇', '得价', '卖', '进款', '收回', '租洋', '解到', '缴', '偿')
EXPENSE_KW = ('购', '买', '付', '送', '赠', '馈', '捐', '助', '给', '裱', '价', '工价', '修', '雇')


def txn_nature(label, evidence, direction):
    s = (label or '') + (evidence or '')
    inc = any(k in s for k in INCOME_KW)
    exp = any(k in s for k in EXPENSE_KW)
    if direction in ('收入', '来'):
        return '收入'
    if direction in ('支出', '去'):
        return '支出'
    if inc and not exp:
        return '收入'
    if exp and not inc:
        return '支出'
    return None  # ambiguous / unknown


# 皖籍 heuristic (reused by 人事): canonical/label hints at Anhui origin.
# 安徽 place-names — multi-char only (avoid ambiguous bare tokens like 太平/池 that collide
# with non-Anhui usages). 徽州府六县 + 安庆/庐州/池州/凤阳 等府县.
ANHUI_KW = ('皖', '安徽', '南陵', '芜湖', '宣城', '泾县', '广德', '阜阳', '六安', '宁国', '当涂',
            '繁昌', '歙县', '徽州', '绩溪', '休宁', '黟县', '祁门', '桐城', '怀宁', '安庆', '合肥',
            '庐江', '贵池', '池州', '寿县', '凤阳', '宿县', '亳州', '涡阳', '蒙城', '怀远', '灵璧',
            '滁州', '和县', '含山', '巢县', '无为', '全椒', '来安', '天长', '旌德', '太湖县')
# High-confidence 皖籍 gazetteer — curated, extend as verified. Source flag (✓) distinguishes
# these from keyword guesses (~). 徐乃昌 字积馀, 祖籍南陵; 吴舜臣 = 南陵收租代理.
# Added (2026-05-28) well-documented 安徽 literati present in corpus — verify before extending:
#   黄宾虹(歙县) 胡朴安(泾县) 许承尧(歙县) 汪孟邹(绩溪) 程演生(怀宁) 刘世珩(贵池).
# Added (2026-06-16, 第5波 皖籍补全) high-interaction 皖人 whose 籍贯 the diary never states
# (so statement-mining can't reach them) and who never sit in a 同乡会 sentence:
#   刘晦之=刘体智(庐江, 善斋, 收藏家) 王揖唐(合肥) 刘秉璋裔. Verified, not guessed.
# Removed '徐淑记': no matching node — 淑记 is a 存款账号/堂号 (evidence "为翦淑记存款"), not a person.
ANHUI_GAZETTEER = {'徐乃昌', '徐积馀', '吴舜臣',
                   '黄宾虹', '胡朴安', '许承尧', '汪孟邹', '程演生', '刘世珩',
                   '刘晦之', '刘体智', '王揖唐'}

# 安徽 place-names for 籍贯 classification (multi-char; 徽州六县 + 安庆/庐州/池州/凤阳/颍州 等府县).
ANHUI_PLACES = {'安徽', '皖', '南陵', '芜湖', '宣城', '泾县', '广德', '六安', '宁国', '当涂',
    '繁昌', '歙县', '徽州', '绩溪', '休宁', '黟县', '祁门', '桐城', '怀宁', '安庆', '合肥',
    '庐江', '贵池', '池州', '寿县', '寿州', '凤阳', '宿县', '宿州', '亳州', '涡阳', '蒙城',
    '怀远', '灵璧', '滁州', '和县', '含山', '巢县', '无为', '全椒', '来安', '天长', '旌德',
    '婺源', '庐州', '颍州', '和州', '太平府', '阜阳', '太湖县'}
# 同乡会/会馆 name fragments — membership is a strong 皖籍 signal (high confidence).
# Anhui-anchored only (generic 同乡会 alone matches 浙江/广东 societies → excluded).
TONGXIANG_KW = ('徽宁', '安徽同乡', '旅沪安徽', '南陵旅沪', '皖同乡', '安徽旅沪',
                '安徽会馆', '徽宁会馆', '新安会馆', '皖省同乡', '皖南同乡',
                '徽州同乡', '宁国同乡', '芜湖同乡', '安徽旅沪同乡')
# Recognized NON-安徽 籍贯 places — used to anchor 籍贯-statement mining (so "〈name〉，〈place〉人"
# matches a real place, not noise like 主人/友人/作冰人) AND to record explicit non-Anhui origin.
NONANHUI_PLACES = {
    '湖北','湖南','江西','山东','河南','广东','广西','四川','浙江','江苏','福建','直隶','河北',
    '山西','陕西','云南','贵州','甘肃','辽宁','吉林','奉天',
    '绍兴','江都','丹徒','无锡','江宁','吴县','湘阴','海宁','温州','乐清','如皋','泰州','宜兴',
    '盐城','金山','丹阳','常熟','武进','镇江','扬州','上海','苏州','杭州','宁波','嘉兴','湖州',
    '嘉定','宝山','松江','太仓','昆山','青浦','南汇','川沙','上虞','余姚','慈溪','鄞县','山阴',
    '会稽','钱塘','仁和','长洲','元和','江阴','常州','淮安','高邮','仪征','兴化','东台','南通',
    '崇明','句容','溧阳','金坛','吴江','震泽','宝应','泰兴','靖江','南昌','九江','贵阳','长沙',
    '武昌','汉阳','番禺','南海','顺德','嘉应','梅县','闽县','侯官','晋江','潮州','大兴','宛平',
    '济南','潍县','胶州','即墨','诸城','曲阜','开封','洛阳','商丘','成都','华阳','遂宁'}
KNOWN_PLACES = ANHUI_PLACES | NONANHUI_PLACES

# ── Chinese-numeral → number (价格 normalization, no re-extraction) ───────────
_CN_DIGIT = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
             '六': 6, '七': 7, '八': 8, '九': 9}
_CN_UNIT = {'十': 10, '百': 100, '千': 1000, '万': 10000, '亿': 100000000}


def _cn_int(s):
    """Parse a Chinese integer string (supports 十/百/千/万). Returns int or None."""
    if not s:
        return None
    if re.fullmatch(r'\d+', s):
        return int(s)
    total = 0
    section = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            u = _CN_UNIT[ch]
            if u >= 10000:
                section = (section + (num or 0)) * u
                total += section
                section = 0
            else:
                if num == 0:
                    num = 1
                section += num * u
            num = 0
        else:
            return None
    return total + section + num


def money2yuan(s):
    """Parse a price token to yuan (float). Handles arabic (17 / 4.41) and
    Chinese 元/角/分 (二元六角五分 → 2.65; 每石二元六角 → 2.6). Returns float or None."""
    if not s:
        return None
    s = str(s)
    m = re.search(r'(\d+(?:\.\d+)?)\s*元', s) or re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*', s)
    if m:
        return float(m.group(1))
    yuan = jiao = fen = 0
    found = False
    my = re.search(r'([零〇一二两三四五六七八九十百千万]+)\s*元', s)
    mj = re.search(r'([零〇一二两三四五六七八九]+)\s*角', s)
    mf = re.search(r'([零〇一二两三四五六七八九]+)\s*分', s)
    if my:
        v = _cn_int(my.group(1)); yuan = v or 0; found = found or v is not None
    if mj:
        v = _cn_int(mj.group(1)); jiao = v or 0; found = True
    if mf:
        v = _cn_int(mf.group(1)); fen = v or 0; found = True
    if found:
        return round(yuan + jiao / 10 + fen / 100, 4)
    # 银两 / 串钱(吊/贯) — approximate 1920s Shanghai conversion to 元 (rough; raw `amount`
    # string is kept alongside amount_num so the native unit stays visible).
    #   1 规银两 ≈ 1.4 元 ;  1 串 = 1 吊 = 1 贯 = 1000 文 ≈ 0.8 元
    mt = re.search(r'([零〇一二两三四五六七八九十百千万\d]+)\s*两', s)
    if mt:
        v = _cn_int(mt.group(1))
        if v is not None:
            return round(v * 1.4, 2)
    mc = re.search(r'([零〇一二两三四五六七八九十百千万\d]+)\s*[串吊贯]', s)
    if mc:
        v = _cn_int(mc.group(1))
        if v is not None:
            return round(v * 0.8, 2)
    # bare Chinese integer (e.g. "卅元" handled via 元 above; try whole-string)
    v = _cn_int(s.replace('元', '').replace('洋', '').strip())
    return float(v) if v is not None else None


# ── Rice-trade parser (稻谷 数量 + 单价, no re-extraction) ────────────────────
# Text is regular: 售稻二百石，每石二元六角 / 收稻650石57斤，售出400石.
_RE_QTY = re.compile(r'([\d零〇一二两三四五六七八九十百千万]+)\s*石')
_RE_UNITP = re.compile(r'每\s*石\s*(?:约|计|售|作|值|得|价)?\s*([\d零〇一二两三四五六七八九十百千万元角分钱洋.]+)')


def parse_rice(text):
    """Return (qty_shi, unit_price_yuan) parsed from txn text, or (None, None)."""
    if not text:
        return (None, None)
    qty = up = None
    mq = _RE_QTY.search(text)
    if mq:
        qty = _cn_int(mq.group(1))
    mu = _RE_UNITP.search(text)
    if mu:
        up = money2yuan(mu.group(1))
    return (qty, up)


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


# ── S1) canonical person resolution (surface/alias → canonical display label) ──
# Root cause of "吴舜臣筛选不全": the 经办人 evidence-fill lexicon held only canonical
# full names (吴舜臣), but rent/sale evidence text names the agent by short alias
# (舜臣/舜老/舜). So `name in blob` missed them, AND when it did fill it wrote the
# matched surface, not the canonical → filter split one person into several buckets.
# Fix: map EVERY alias → its primary PER id, and always emit the canonical label.
HONORIFIC_SUFFIX = ('先生', '观察', '太史', '中堂', '大人', '公', '老', '翁', '丈',
                    '兄', '弟', '君', '氏', '丈人')


def _strip_honorific(s):
    s = (s or '').strip()
    for suf in HONORIFIC_SUFFIX:
        if len(s) > len(suf) and s.endswith(suf):
            return s[:-len(suf)]
    return s


# alias/surface → primary PER id; ambiguous aliases (≥2 distinct primaries) dropped.
_surface_to_primary = {}
_surface_ambig = set()
for _n in src['nodes']:
    if _n.get('entity_type') != '人':
        continue
    _pid = redirect(_n['id'])
    _md = _n.get('metadata') or {}
    _forms = {_n.get('label'), _md.get('canonical')}
    for _sf in (_md.get('surface_forms') or []):
        _forms.add(_sf.get('surface'))
    _variants = set()
    for _s in _forms:
        if _s:
            _variants.add(_s.strip())
            _variants.add(_strip_honorific(_s))
    for _v in _variants:
        if not _v or len(_v) < 2:
            continue
        if _v in _surface_to_primary and _surface_to_primary[_v] != _pid:
            _surface_ambig.add(_v)
        else:
            _surface_to_primary[_v] = _pid
for _v in _surface_ambig:
    _surface_to_primary.pop(_v, None)

# manual overrides for aliases the auto-seed can't link (surface → canonical label)
CANON_OVERRIDE = {}


def canonicalize_person(surface):
    """Surface/alias string → canonical display label. Unchanged if unresolved."""
    if not surface:
        return surface
    s = surface.strip()
    if s in CANON_OVERRIDE:
        return CANON_OVERRIDE[s]
    pid = _surface_to_primary.get(s) or _surface_to_primary.get(_strip_honorific(s))
    if pid:
        return nodes_by_id.get(pid, {}).get('label') or s
    return s


# raw source chunk bodies by date (shared, read once) — Tier-2 reconciliation
# (rice 单价 backfill, 事业 source-text coverage/timelines). No re-extraction.
_SRC_BODY = {}
for _p in sorted((ROOT / 'data' / 'poc_200').glob('*.md')):
    _m = re.search(r'(\d{4}-\d{2}-\d{2})', _p.stem)
    if _m:
        try:
            _SRC_BODY[_m.group(1)] = _p.read_text(encoding='utf-8')
        except Exception:
            pass


def _strip_fm(t):
    """Drop the YAML frontmatter block (author:徐乃昌 / source_pdf:徐乃昌日记… pollute
    person scans) and the markdown date heading, leaving the diary body only."""
    if t.startswith('---'):
        e = t.find('\n---', 3)
        if e != -1:
            t = t[e + 4:]
    return re.sub(r'^\s*#[^\n]*\n', '', t.lstrip(), count=1)


# frontmatter-stripped body (used by 同乡会 co-attendance tagging + 南陵县志 长编 +
# any whole-entry person scan, so frontmatter 徐乃昌日记/author never false-matches).
_BODY = {d: _strip_fm(t) for d, t in _SRC_BODY.items()}


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
(out_dir / 'overview.json').write_text(json.dumps(overview, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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
    cp_evidence_parts = []     # 商务/交易边的 evidence_text — 供 nature 判定 (购/售/估/当)
    for direction, e in edges_by_node.get(n['id'], []):
        if e.get('relation') in ('商务', '资助', '转交') and (e.get('metadata') or {}).get('evidence_text'):
            cp_evidence_parts.append(e['metadata']['evidence_text'])
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
    txn_details = md.get('txn_details')
    if not isinstance(txn_details, dict):
        txn_details = {}
    evidence = (md.get('surface_forms') or [{}])[0].get('surface', n.get('label', ''))
    # 经办人: person counterparties linked by trade/funding/relay relations.
    AGENT_RELS = {'商务', '资助', '转交', '赠', '受赠'}
    _agent_cps = [cp for cp in counterparties
                  if cp.get('type') == '人' and cp.get('relation') in AGENT_RELS]
    agents = [canonicalize_person(cp['label']) for cp in _agent_cps]
    agent_pids = [cp['id'] for cp in _agent_cps]
    cp_evidence_blob = ' '.join(cp_evidence_parts)
    _txt = (n.get('label') or '') + ' ' + (evidence or '')
    amount_num = money2yuan(txn_details.get('amount'))
    qty_shi, unit_price_yuan = parse_rice(_txt)
    if unit_price_yuan is None:  # unit price sometimes landed in the amount slot, already
        _amt = txn_details.get('amount')             # per-石 ("3.2元/石" 价洋三元二角 / 每石X)
        if isinstance(_amt, str) and ('每石' in _amt or '/石' in _amt or '元/石' in _amt):
            unit_price_yuan = money2yuan(_amt)
            amount_num = None                         # it's a unit price, not a total
    # 稻谷交易: 稻/谷 keyword, or a parsed 石-quantity (number+石 is the grain measure).
    # Bare '石' rejected (book titles 石柱记/石印, names 石铭/葱石 — none carry a number+石).
    # 租洋/房租 without 稻/谷/石量 excluded: those are money/property rent, not grain.
    is_rice = ('稻' in _txt or '谷' in _txt or qty_shi is not None)
    # DEBUG-① (图谱改进0605 "售稻单价计算错误", e.g. 1934-07-12 售稻一百石共二百九十元):
    # when a rice row has 数量 + 总价 but no 每石 token of its own, derive 单价 = 总价÷石数
    # from THIS row's own numbers. Without it, the day-level 每石 backfill below copies one
    # deal's 每石 onto every rice row of the day, so multi-deal days (期稻@1.7 + 售稻@2.9)
    # collapse to a single wrong price. Per-row compute prices each deal independently.
    unit_price_source = 'parse' if unit_price_yuan is not None else None
    _amt_str = txn_details.get('amount') if isinstance(txn_details.get('amount'), str) else ''
    if (unit_price_yuan is None and is_rice and amount_num and qty_shi
            and qty_shi >= 10                        # real grain lots are tens+ of 石; qty=1 = mis-parse
            and not any(c in _amt_str for c in ('每', '石', '扯', '约', '/'))):  # amount already per-石, not a total
        _up = round(amount_num / qty_shi, 2)
        if 0.8 <= _up <= 8.0:                        # plausible 1920s-30s 稻谷单价 band (元/石)
            unit_price_yuan = _up
            unit_price_source = 'computed'
    # nature: keyword scan first; fall back to the directional counterparty relation type
    # (受赠=收到 → 收入; 赠/资助=给出 → 支出). Typed signal, independent of wording.
    nature = txn_nature(n.get('label'), (evidence or '') + ' ' + cp_evidence_blob, txn_details.get('direction'))
    if nature is None:
        rels = {cp.get('relation') for cp in counterparties}
        if '受赠' in rels:
            nature = '收入'
        elif '赠' in rels or '资助' in rels:
            nature = '支出'
    txns.append({
        'id': n['id'],
        'label': n.get('label'),
        'date': n.get('captured_at'),
        'source_file': normalize_source(n.get('source_file')),
        'evidence': evidence,
        'people': counterparties,
        'item': txn_details.get('item'),
        'quantity': txn_details.get('quantity'),
        'amount': txn_details.get('amount'),
        'amount_num': amount_num,                       # normalized 价格 (元)
        'direction': txn_details.get('direction'),
        'nature': nature,
        'agent': agents[0] if agents else None,
        'agents': agents,
        'agent_source': 'edge' if agents else None,
        '_agent_pids': agent_pids,
        'page': page_for(n.get('captured_at')),
        'is_rice': is_rice,
        'qty_shi': qty_shi,                             # 稻谷数量 (石)
        'unit_price_yuan': unit_price_yuan,             # 稻谷单价 (元/石)
        'unit_price_source': unit_price_source,         # parse | computed | source_text | synth
    })
# ── 经办人 fallback (P4a + S1): many rent/sale txns name the handling agent only in the
# evidence text (代售/经手/汇 by 舜臣). Build the scan lexicon as alias→canonical pairs
# (NOT canonical-only), seeded from the persons who already appear as structured agents
# (primary id freq≥3, excluding the diarist — he is principal, not a handling agent).
# Scanning ALL aliases catches short forms like 舜臣/舜老; emitting the canonical label
# unifies them so the 经办人 filter no longer splits one person across buckets.
DIARIST = '徐乃昌'
_agent_pid_freq = Counter(pid for t in txns for pid in (t.get('_agent_pids') or [])
                          if nodes_by_id.get(pid, {}).get('label') != DIARIST)
FREQ_AGENT_PIDS = {pid for pid, c in _agent_pid_freq.items() if c >= 3}
AGENT_ALIASES = sorted(
    ((alias, nodes_by_id.get(pid, {}).get('label') or alias)
     for alias, pid in _surface_to_primary.items()
     if pid in FREQ_AGENT_PIDS and len(alias) >= 2
     and nodes_by_id.get(pid, {}).get('label') != DIARIST),
    key=lambda x: -len(x[0]))            # longest alias first → 吴舜臣 beats 舜臣

# DEBUG (图谱改进0615 "吴舜臣抓得不全"): the 经办人 of a 稻/租 row is whoever is named in
# the 稻/租 SENTENCE — not an incidental name elsewhere that day. Old whole-body scan let
# a social visit (鲍子丹) or a same-day counterparty (丁子盈) steal attribution from 舜臣
# (user's anchor 1920-08-13: 复舜臣书…将稻全行售出 was tagged 鲍子丹). 吴舜臣 (舜臣/舜老) is
# Xu's standing 南陵收租代理 → when he is in a rent sentence he IS the 经办人, overriding any
# edge-linked 买主 or the diarist. Sentence-level (split on 。\n/) so 舜臣+稻 in one breath
# bind even when separated by commas.
# Precise rent/grain tokens. Bare 租/谷 excluded — they fire on 租界/房租/租屋(building rent),
# 春谷(芜湖)/山谷/孔洪谷(names/places), 《上海租界问题》(book). Kept tokens are unambiguously
# land-rent/grain: 稻* / 收租·交租·欠租 / 租稻·稻租 / 租息·租簿·经租·租洋 / 积谷·储谷 / 完粮·押板 /
# 总账·总簿 (舜臣's rent accounts — user's 吴舜臣 table lists 总账 explicitly).
_RENT_SENT_KW = ('收租', '交租', '欠租', '租稻', '稻租', '售稻', '卖稻', '收稻', '解稻',
                 '租息', '租簿', '经租', '租洋', '完粮', '押板', '每石', '积谷', '储谷',
                 '稻价', '稻款', '稻洋', '借稻', '期稻', '总账', '总簿')
_SHUN = ('吴舜臣', '舜臣', '舜老')


def _rent_agent_in_body(body):
    """Canonical 收租经办人 for a rent/grain day. 吴舜臣 is Xu's STANDING 南陵收租代理 —
    daily entries are short, so his presence anywhere in the entry means the rent business
    is his (the report is often split "覆舜臣书。稻洋收到…" across sentences). Check him
    whole-entry FIRST; only if absent fall back to another known agent named in a 稻/租
    sentence (sentence-scoped so an incidental social-visit name isn't credited)."""
    if not body:
        return None
    if any(a in body for a in _SHUN):
        return '吴舜臣'
    for sent in re.split(r'[。\n/]', body):
        if any(k in sent for k in _RENT_SENT_KW):
            for alias, canon in AGENT_ALIASES:
                if alias in sent:
                    return canon
    return None


_agent_evidence_fill = 0
_agent_body_fill = 0
for t in txns:
    _cur = t.get('agent')
    # DEBUG-③④ (图谱改进0605 "1925-03-30 经办人吴舜臣漏掉"): a 收租/稻 row whose only
    # structured agent is the DIARIST (徐乃昌 = principal, not the handling 经办人) was kept
    # as-is and never body-scanned, so the real 经办人 (覆吴舜臣书 → 吴舜臣) was lost. Treat
    # diarist-only agency on estate/grain rows as "no handling agent" → fall through to the
    # evidence/body scan below. Non-estate diarist rows (book purchases) keep 徐乃昌.
    if _cur and _cur != DIARIST:
        t['agent'] = canonicalize_person(_cur)
        t['agents'] = [canonicalize_person(a) for a in (t.get('agents') or [])]
        continue
    blob = (t.get('label') or '') + ' ' + (t.get('evidence') or '')
    hit = next((canon for alias, canon in AGENT_ALIASES if alias in blob), None)
    if hit:
        t['agent'] = hit
        t['agents'] = [hit]
        t['agent_source'] = 'evidence'
        _agent_evidence_fill += 1
        continue
    # Tier-2 (S1b): the 经办人 of 南陵 rent/grain 账单 is often named elsewhere in
    # the chunk body, not in the txn's own evidence span (the user's headline case:
    # 1920-03-12 售稻二百石 handled by 舜臣). For estate/grain txns only, scan the
    # source body for a known grain agent. Restricted scope avoids over-attribution.
    _estate = (t.get('is_rice')
               or any(k in blob for k in ('收租', '租洋', '房租', '佃', '业户', '田产',
                                          '田亩', '湖田', '圩田', '完粮'))
               or ('田' in blob and '田黄' not in blob))   # 田黄印 = seal stone, not farmland
    if _estate:
        body = _SRC_BODY.get(t.get('date') or '', '')
        bhit = _rent_agent_in_body(body)
        if bhit:
            t['agent'] = bhit
            t['agents'] = [bhit]
            t['agent_source'] = 'body'
            _agent_body_fill += 1

# DEBUG (0615) Fix-A: re-attribute rice rows whose 稻/租 sentence names 吴舜臣 but whose
# agent came from an incidental edge/counterparty (买主) or the diarist. Overrides agent
# only (original counterparty stays in `people`). Catches the 9 mis-attributed rice rows
# incl. user anchors 1920-08-13 / 1936-09-21 / 1937-07-11. is_rice-scoped → safe.
_rice_reattrib = 0
for t in txns:
    if not t.get('is_rice') or not t.get('date'):
        continue
    ra = _rent_agent_in_body(_SRC_BODY.get(t['date'], ''))
    if ra and t.get('agent') != ra:
        t['agent'] = ra
        t['agents'] = [ra]
        t['agent_source'] = 'rent_sentence'
        _rice_reattrib += 1

for t in txns:
    t.pop('_agent_pids', None)

# ── S4: 稻谷单价 recall from source chunk text (no re-extraction) ──────────────
# 每石<价> usually sits in the chunk body, not in the rice txn node's own label,
# so parse_rice(node text) misses it (36/39 baseline misses were parser-gaps,
# 3 had no txn node). Per date: take the source 每石 price, then (a) backfill any
# rice txn on that day lacking unit_price, else (b) synthesize a rice price row.
# DEBUG-① guard (图谱改进0605 "1921-09-29 单价误抓"): a 每石<价> is a RICE price only if
# its immediate context isn't a per-石 price of PAPER/printing (印《玉历钞传》三千部, 每部
# 十一石, 每石一元四角 = paper reams, not grain — produced the bogus rice_synth_1921-09-29).
# Skip 每石 matches whose vicinity carries paper/print markers; take the first clean one.
# Markers also cover freight/goods 每石 (退货每石四角 = shipping rate, not grain — 1921-11-24).
_NONRICE_NEAR = ('纸', '令', '印', '部', '装订', '扣', '墨', '笔', '工价', '裱', '货', '运')
_rice_price_by_date = {}
for _d, _body in _SRC_BODY.items():
    _up = None
    for _mu in _RE_UNITP.finditer(_body):
        _ctx = _body[max(0, _mu.start() - 15): _mu.end() + 6]
        if any(k in _ctx for k in _NONRICE_NEAR):
            continue                                 # 每石 is paper/freight/printing, not 稻谷
        _v = money2yuan(_mu.group(1))
        if _v and 0.5 <= _v <= 8.0:                  # plausible 稻谷单价 band — rejects mis-parses
            _up = _v
            break
    if _up:
        _mq = _RE_QTY.search(_body)
        _rice_price_by_date[_d] = (_up, _cn_int(_mq.group(1)) if _mq else None)
_txns_by_date = defaultdict(list)
for t in txns:
    if t.get('date'):
        _txns_by_date[t['date']].append(t)
_price_backfill = _price_synth = 0
for _d, (_up, _qs) in _rice_price_by_date.items():
    _rice_here = [t for t in _txns_by_date.get(_d, []) if t.get('is_rice')]
    _already = [t for t in _rice_here if t.get('unit_price_yuan') is not None]
    if _already:
        continue                                     # day's rice price already captured
    if _rice_here:                                   # (a) backfill existing rice txn
        for t in _rice_here:
            t['unit_price_yuan'] = _up
            if t.get('qty_shi') is None:
                t['qty_shi'] = _qs
            t['unit_price_source'] = 'source_text'
        _price_backfill += 1
    else:                                            # (b) synthesize a rice price record
        _agent = (_rent_agent_in_body(_SRC_BODY[_d])      # rent-sentence 经办人 (0615 fix)
                  or next((canon for alias, canon in AGENT_ALIASES if alias in _SRC_BODY[_d]), None))
        txns.append({
            'id': f'rice_synth_{_d}', 'label': f'稻谷售价 每石{_up}元',
            'date': _d, 'source_file': f'{_d}.md',
            'evidence': (_RE_UNITP.search(_SRC_BODY[_d]).group(0) if _RE_UNITP.search(_SRC_BODY[_d]) else ''),
            'people': [], 'item': '稻谷', 'quantity': (f'{_qs}石' if _qs else None),
            'amount': None, 'amount_num': None, 'direction': None, 'nature': '收入',
            'agent': _agent, 'agents': [_agent] if _agent else [],
            'agent_source': 'evidence' if _agent else None,
            'page': page_for(_d), 'is_rice': True, 'qty_shi': _qs,
            'unit_price_yuan': _up, 'unit_price_source': 'synth',
        })
        _price_synth += 1

# DEBUG (0615) Fix-B: synthesize a 收租 账单 row for days where 吴舜臣 (舜臣/舜老) is named in
# a 稻/租 sentence but no 吴舜臣 transaction node exists (correspondence-only rent reports:
# 覆舜臣书。稻洋收到… / 舜臣来书…年成…). Closes the gap between 经办人=吴舜臣 (was 242) and his
# true 收租 involvement. STRICT: 舜 must sit in the rent sentence itself (high precision).
_shun_acct_days = set(t['date'] for t in txns if t.get('agent') == '吴舜臣' and t.get('date'))
_shun_synth = 0
for _d, _body in _SRC_BODY.items():
    if _d in _shun_acct_days or not any(a in _body for a in _SHUN):
        continue
    _sents = re.split(r'[。\n/]', _body)
    # evidence = the rent sentence (prefer one naming 舜); skip days with no rent content
    _sent = next((s.strip() for s in _sents
                  if any(k in s for k in _RENT_SENT_KW) and any(a in s for a in _SHUN)), None) \
        or next((s.strip() for s in _sents if any(k in s for k in _RENT_SENT_KW)), None)
    if not _sent:
        continue
    _item = '总账' if '总账' in _sent else ('卖稻' if ('卖稻' in _sent or '售稻' in _sent) else '稻租')
    _nat = '收入' if any(k in _sent for k in ('收', '售', '卖', '汇', '解', '缴', '完')) else None
    txns.append({
        'id': f'shun_rent_{_d}', 'label': _sent[:40], 'date': _d, 'source_file': f'{_d}.md',
        'evidence': _sent[:120], 'people': [], 'item': _item, 'quantity': None,
        'amount': None, 'amount_num': None, 'direction': None, 'nature': _nat,
        'agent': '吴舜臣', 'agents': ['吴舜臣'], 'agent_source': 'rent_sentence_synth',
        'page': page_for(_d), 'is_rice': True, 'qty_shi': None,
        'unit_price_yuan': None, 'unit_price_source': None,
    })
    _shun_synth += 1

# 售稻 flag (新需求 0605/0615 "导出账单=》售稻信息列表"): rice rows that are SALES (售/卖),
# i.e. disposal of grain for cash — distinct from 收稻/收租 (collecting rent in grain).
# One pass so it also covers the rice_synth / shun_rent synthesized rows.
_rice_sale_n = 0
for t in txns:
    _bl = (t.get('label') or '') + (t.get('evidence') or '')
    t['is_rice_sale'] = bool(t.get('is_rice') and any(k in _bl for k in ('售', '卖')))
    _rice_sale_n += t['is_rice_sale']

txns.sort(key=lambda t: t.get('date', '') or '')
(out_dir / 'transactions.json').write_text(json.dumps(txns, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'  售稻 sale rows: {_rice_sale_n}')
print(f'  稻谷单价: backfilled {_price_backfill} days, synthesized {_price_synth} '
      f'(source 每石 prices on {len(_rice_price_by_date)} days)')
print(f'  吴舜臣经办人: rice re-attributed {_rice_reattrib}, correspondence rows synthesized '
      f'{_shun_synth} → {sum(1 for t in txns if t.get("agent") == "吴舜臣")} total rows '
      f'on {len(set(t["date"] for t in txns if t.get("agent") == "吴舜臣"))} days')
print(f'  经办人: {sum(1 for t in txns if t.get("agent"))}/{len(txns)} filled '
      f'(+{_agent_evidence_fill} via evidence, +{_agent_body_fill} via body-scan, '
      f'alias-lexicon={len(AGENT_ALIASES)} for {len(FREQ_AGENT_PIDS)} persons); '
      f'nature: {sum(1 for t in txns if t.get("nature"))}/{len(txns)}')


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
    json.dumps({'nodes': per_nodes_deduped, 'edges': per_edges_deduped}, ensure_ascii=False, separators=(',', ':')),
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
# "unmapped" = no city AND not a placed venue (venue_dots cover VENUE_COORDS labels on the map).
unmapped = Counter(v['location_label'] for v in visits
                   if not v['resolved_city'] and v['location_label'] not in VENUE_COORDS)

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
}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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
(out_dir / 'books.json').write_text(json.dumps(books, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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

(out_dir / 'people_profiles.json').write_text(json.dumps(per_profile, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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
(out_dir / 'misc_entities.json').write_text(json.dumps(misc_profiles, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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

# ── 称呼演变 (honorific shift, e.g. 舜臣→舜老) — surfaces xlsx QA #3, discoverable in 统计 ──
def _is_honorific(s):
    return s.endswith(('老', '翁', '丈', '公', '叟', '伯')) or '先生' in s
honorific_shifts = []
for pid, pr in per_profile.items():
    ae = pr.get('alias_evolution') or []
    if len(ae) < 2:
        continue
    plain = [a for a in ae if not _is_honorific(a['surface'])]
    honor = [a for a in ae if _is_honorific(a['surface'])]
    if not plain or not honor:
        continue
    p0 = min(plain, key=lambda a: a.get('first') or '9999')
    h0 = min(honor, key=lambda a: a.get('first') or '9999')
    # honorific adopted strictly later; forms genuinely differ (not one a substring of the
    # other — skips 程选公 vs 程选公(瑞铨)). Aliases are all the same person (same profile).
    if ((h0.get('first') or '') > (p0.get('first') or '')
            and h0['surface'] not in p0['surface'] and p0['surface'] not in h0['surface']):
        honorific_shifts.append({
            'id': pid, 'label': pr.get('label'),
            'from': p0['surface'], 'from_date': p0.get('first'),
            'to': h0['surface'], 'to_date': h0.get('first'), 'to_last': h0.get('last'),
        })
honorific_shifts.sort(key=lambda x: x.get('to_date') or '')

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
    'honorific_shifts': honorific_shifts,
}
(out_dir / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'  称呼演变 (honorific shifts): {len(honorific_shifts)}')


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
(out_dir / 'events.json').write_text(json.dumps(events_out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

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
    # 'page' = corrected 原书页码 (via page_map); 'source_pages' kept = raw part-local pdf index.
    chunks[date_key] = {'body': body, 'entities': [], 'lunar_date': lunar, 'source_pdf': pdf,
                        'source_pages': pages, 'page': page_for(date_key)}

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
(out_dir / 'chunks.json').write_text(json.dumps(chunks_out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

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

(out_dir / 'kin.json').write_text(json.dumps(kin_edges_out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'wrote {len(kin_edges_out)} kin edges')

# ── 10) 人事 (personnel registry) ────────────────────────────────────────────
# Per deduped PER: 团体归属 (属于), 是否皖籍 (heuristic), activity log (事由=evidence).
# Covers xlsx 人事 columns: 人物 / 事由 / 身份(归属团体) / 是否皖籍 / 页码 / 日期.
def is_anhui(*texts):
    blob = ' '.join(t for t in texts if t)
    return any(k in blob for k in ANHUI_KW)

# org membership per primary PER (属于 edges, person→团体)
orgs_by_per = defaultdict(list)
for e in src['edges']:
    if e.get('relation') != '属于':
        continue
    s = e.get('source'); t = e.get('target')
    sn = nodes_by_id.get(s, {}); tn = nodes_by_id.get(t, {})
    if sn.get('entity_type') == '人' and tn.get('entity_type') == '团体':
        p = redirect(s)
        lbl = tn.get('label')
        if lbl and lbl not in orgs_by_per[p]:
            orgs_by_per[p].append(lbl)

# ── 籍贯 mining (no re-extraction): the diary states native place in bio intros like
# "陈乃乾，号慎初，海宁人" / "李子瑾瑜，温州乐清人" / "李子廊…字无庸，湘阴人". Strategy: anchor on a
# KNOWN place name (skips noise 主人/友人/作冰人), then attribute it to the person whose OWN alias
# sits in the ~16-char window just before it. Explicit non-Anhui 籍贯 is authoritative (overrides keyword).
alias_to_pid = {}
_ambig = set()
for _pid, _ref in primary_node_ref.items():
    _md = _ref.get('metadata') or {}
    for _s in {x for x in [_ref.get('label'), _md.get('canonical'), *primary_aliases.get(_pid, [])] if x and len(x) >= 2}:
        if _s in alias_to_pid and alias_to_pid[_s] != _pid:
            _ambig.add(_s)
        else:
            alias_to_pid[_s] = _pid
for _s in _ambig:
    alias_to_pid.pop(_s, None)

_PLACE_ALT = '|'.join(sorted(KNOWN_PLACES, key=len, reverse=True))
RX_PLACE = re.compile(r'(' + _PLACE_ALT + r')人')
jiguan_by_pid = {}   # pid → stated 籍贯 place
for _mf in sorted((ROOT / 'data' / 'poc_200').glob('*.md')):
    _body = _mf.read_text(encoding='utf-8')
    for m in RX_PLACE.finditer(_body):
        win = _body[max(0, m.start() - 16):m.start()]
        best, best_end = None, -1
        for L in (4, 3, 2):
            for i in range(len(win) - L + 1):
                if win[i:i + L] in alias_to_pid and i + L > best_end:
                    best, best_end = alias_to_pid[win[i:i + L]], i + L
        if best is not None:
            jiguan_by_pid[best] = m.group(1)   # nearest occurrence in this file wins

# ── 同乡会 co-attendance → 皖籍 (event-based, no re-extraction) ─────────────────
# 「参加各种皖省同乡会、徽宁同乡会、安徽旅沪同乡会等都是皖籍」(0616 第5波①). When a diary day names an
# Anhui native-place society, the people listed AROUND that name are co-attendees → tagged
# 皖籍 (source=tongxiang_event). Anchored to Anhui societies only (TONGXIANG_KW), so 浙江/广东
# 同乡会 never leak. PROXIMITY (window around the society name, not whole entry): a roster sits
# beside "徽宁同乡会公宴…座中…"; an incidental mention elsewhere in the day (a wedding, a letter
# about a 同乡会 dispute) won't sweep in unrelated names. Authoritative non-Anhui 籍贯 still wins
# (classifier tier 1 precedes this). Drop generic role-words that extraction left as "persons".
_NONPERSON_ALIAS = {'冰人', '作冰人', '主人', '友人', '同乡', '督军', '张督军', '知事', '太守', '局长'}
_alias_keys = [a for a in alias_to_pid if len(a) >= 2 and a not in _NONPERSON_ALIAS]
_alias_rx = re.compile('|'.join(re.escape(a) for a in
                                sorted(_alias_keys, key=len, reverse=True))) if _alias_keys else None
_TX_RX = re.compile('|'.join(re.escape(k) for k in sorted(TONGXIANG_KW, key=len, reverse=True)))
tongxiang_event_pids = set()
tongxiang_event_days = []
for _d, _b in _BODY.items():
    if not _TX_RX.search(_b):
        continue
    # join short adjacent clauses around the society name into one roster sentence; tag persons
    # named WITH the society (同一句), so a colophon/gift in the next sentence isn't swept in.
    _parts = re.split(r'(?<=[。！？\n])|\s{2,}', _b)        # sentence-level (keep 、，inside a roster)
    hit = False
    for _s in _parts:
        if _TX_RX.search(_s):
            hit = True
            if _alias_rx:
                for _a in set(_alias_rx.findall(_s)):
                    tongxiang_event_pids.add(alias_to_pid[_a])
    if hit:
        tongxiang_event_days.append(_d)

def _place_is_anhui(pl):
    return (pl in ANHUI_PLACES) or any(p in pl or pl in p for p in ANHUI_PLACES)

def anhui_classify(pid, names, orgs):
    """Tiered, highest-confidence first. Returns (is_anhui, source). A statement is
    authoritative both ways (so an explicit non-Anhui 籍贯 overrides keyword guesses)."""
    if pid in jiguan_by_pid:
        return (_place_is_anhui(jiguan_by_pid[pid]), 'statement')
    if any(any(k in o for k in TONGXIANG_KW) for o in orgs):
        return (True, 'tongxianghui')
    if pid in tongxiang_event_pids:                    # co-attended an Anhui 同乡会
        return (True, 'tongxiang_event')
    if any(n in ANHUI_GAZETTEER for n in names):
        return (True, 'gazetteer')
    if is_anhui(*names, *orgs):
        return (True, 'keyword')
    return (False, None)

renshi = []
for pid, ref in primary_node_ref.items():
    md = ref.get('metadata') or {}
    aliases = primary_aliases.get(pid, [])
    member_ids = set(primary_orig_ids.get(pid, [pid]))
    acts = []
    seen_act = set()
    for mid in member_ids:
        for direction, e in edges_by_node.get(mid, []):
            other_id = e['target'] if direction == 'out' else e['source']
            on = nodes_by_id.get(redirect(other_id) if nodes_by_id.get(other_id, {}).get('entity_type') == '人' else other_id, {})
            emd = e.get('metadata') or {}
            date = e.get('source_location')
            evid = emd.get('evidence_text')
            k = (date, e.get('relation'), evid)
            if k in seen_act:
                continue
            seen_act.add(k)
            acts.append({
                'date': date,
                'relation': e.get('relation'),
                'matter': evid,                       # 事由
                'counterpart': on.get('label'),
                'page': page_for(date),
            })
    acts.sort(key=lambda a: a.get('date') or '')
    rel_counts = {}
    for a in acts:
        r = a.get('relation')
        if r:
            rel_counts[r] = rel_counts.get(r, 0) + 1
    rel_summary = '·'.join(f'{r}{c}' for r, c in sorted(rel_counts.items(), key=lambda kv: -kv[1])[:6])
    orgs = orgs_by_per.get(pid, [])
    names = [n for n in [ref.get('label'), md.get('canonical'), *aliases] if n]
    is_ah, ah_src = anhui_classify(pid, names, orgs)
    renshi.append({
        'id': pid,
        'label': ref.get('label'),
        'canonical': md.get('canonical'),
        'aliases': aliases,
        'orgs': orgs,                                  # 身份(归属团体)
        'is_anhui': is_ah,
        'anhui_source': ah_src,                        # statement|tongxianghui|gazetteer|kinship|keyword
        'jiguan': jiguan_by_pid.get(pid),              # explicit native place mined from diary (if any)
        'interactions': len(acts),
        'first_seen': acts[0]['date'] if acts else None,
        'last_seen': acts[-1]['date'] if acts else None,
        'rel_summary': rel_summary,                    # 事由概览(关系类型分布); 完整事由经办通过 profile drawer (sample_edges/原文)
    })

# ── kinship propagation: a relative of a HIGH-confidence 皖籍 person is 皖籍 too.
# One hop, from {statement,tongxianghui,tongxiang_event,gazetteer} only (not keyword) to avoid amplifying guesses.
_by_id = {r['id']: r for r in renshi}
_confident = {r['id'] for r in renshi if r['is_anhui']
              and r['anhui_source'] in ('statement', 'tongxianghui', 'tongxiang_event', 'gazetteer')}
for ke in kin_edges_out:
    for me, other in ((ke['source'], ke['target']), (ke['target'], ke['source'])):
        r = _by_id.get(me)
        if r and not r['is_anhui'] and other in _confident:
            r['is_anhui'] = True
            r['anhui_source'] = 'kinship'

renshi.sort(key=lambda r: -r['interactions'])
(out_dir / 'renshi.json').write_text(json.dumps(renshi, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
_src_counts = Counter(r['anhui_source'] for r in renshi if r['is_anhui'])
_nonah = sum(1 for r in renshi if r.get('jiguan') and not _place_is_anhui(r['jiguan']))
print(f'wrote {len(renshi)} 人事 records; 皖籍={sum(1 for r in renshi if r["is_anhui"])} by source {dict(_src_counts)} '
      f'(籍贯 mined for {len(jiguan_by_pid)} persons; {_nonah} explicit non-皖)')

# ── 11) 事业 (career / enterprise — rule-based derivation) ────────────────────
# No 事业 entity type in schema; cluster existing BOOK/ORG/TXN by keyword.
# Covers xlsx 事业 columns: 项目 / 内容 / 经办人 / 花费 / 页码 / 日期.

# project rules: (项目名, 类型, [label keywords])
# (项目名, 类型, [label keywords], text_scan)
# text_scan=True → also gather day-coverage from RAW CHUNK TEXT (Tier-2, no
# re-extraction), so days the source mentions the topic but extraction surfaced
# no matching entity still join the project. The 5 categories below come from
# 图谱改进0531.xlsx 事业补充.
PROJECT_RULES = [
    ('编《南陵志》', '编纂', ['南陵志', '修志局', '筹备修志局', '志局'], False),
    ('闺阁诗著述', '著述', ['闺阁', '诗钞', '诗人征略', '闺秀', '香咳'], False),
    ('大生纱厂实业', '实业', ['大生纱厂', '大生'], False),
    ('裕中纱厂实业', '实业', ['裕中纱厂'], False),
    ('溥益纱厂实业', '实业', ['溥益纱厂'], False),
    ('当涂矿业', '实业', ['汉冶萍', '当涂矿', '繁昌矿', '宝兴铁矿'], False),
    ('垦务·万顷湖/万春湖', '垦务', ['万顷湖', '万春湖', '盐垦', '湖田', '圩田', '垦务'], True),
    ('赈务', '赈务', ['赈', '义振', '放赈', '急赈', '赈款', '赈灾', '极贫'], True),
    ('编《安徽通志》', '编纂', ['安徽通志', '通志局', '皖志局'], True),
    ('同乡会·会馆', '社团', ['同乡会', '徽宁会馆', '旅沪安徽', '南陵旅沪', '皖同乡', '安徽旅沪'], True),
    ('家族事务', '家族', ['三太太', '大太太', '二太太', '族叔', '族长', '族祖', '族兄', '族弟',
                         '族侄', '堂兄', '堂弟', '堂叔', '堂侄', '本家', '祠堂', '宗祠', '祖茔',
                         '祭祖', '扫墓', '南陵原籍'], True),
]


def _text_hits(kws):
    """Tier-2: source chunk dates mentioning any kw → [{date, page, snippet}]."""
    hits = []
    for d, body in _SRC_BODY.items():
        pos = min((body.find(k) for k in kws if k in body), default=-1)
        if pos >= 0:
            snip = body[max(0, pos - 8):pos + 32].replace('\n', ' ').strip()
            hits.append({'date': d, 'page': page_for(d), 'snippet': snip})
    hits.sort(key=lambda h: h['date'])
    return hits


def _shiye_record(proj, ptype, members, stock=False, text_hits=None):
    seen = set(); uniq = []
    for n in members:
        if n['id'] not in seen:
            seen.add(n['id']); uniq.append(n)
    members = uniq
    txn_items, persons, dates, pages, total = [], set(), [], set(), 0.0
    for n in members:
        d = n.get('captured_at')
        if d:
            dates.append(d)
            if page_for(d):
                pages.add(page_for(d))
        if n.get('entity_type') == '交易':
            td = n.get('metadata') or {}
            amt = (td.get('txn_details') or {}).get('amount') if isinstance(td.get('txn_details'), dict) else None
            av = money2yuan(amt)
            if av:
                total += av
            txn_items.append({'label': n.get('label'), 'amount': amt, 'date': d})
        for direction, e in edges_by_node.get(n['id'], []):
            other = e['target'] if direction == 'out' else e['source']
            on = nodes_by_id.get(other, {})
            if on.get('entity_type') == '人':
                persons.add(nodes_by_id.get(redirect(other), on).get('label'))
    # Tier-2 source dates fold into the project's day/page coverage + a timeline.
    text_hits = text_hits or []
    member_dates = set(d for d in dates if d)
    for h in text_hits:
        member_dates.add(h['date'])
        if h['page']:
            pages.add(h['page'])
    dates = sorted(member_dates)
    return {
        'project': proj,
        'type': ptype,
        'member_count': len(members),
        'orgs': sorted({n.get('label') for n in members if n.get('entity_type') == '团体'}),
        'books': sorted({n.get('label') for n in members if n.get('entity_type') == '书籍'}),
        'txns': txn_items,
        'cost_arabic_sum': round(total, 2) if total else None,
        'agents': sorted({canonicalize_person(p) for p in persons if p}),
        'date_range': [dates[0], dates[-1]] if dates else None,
        'pages': sorted(pages),
        'member_dates': dates,                       # all covered chunk dates (node ∪ source)
        'source_chunk_count': len(text_hits),        # Tier-2 chunk hits
        'timeline': text_hits[:300],                 # 事件脉络 (date/page/snippet)
        'auto': ptype not in ('编纂', '著述', '垦务', '赈务', '社团', '家族')
                and proj not in [r[0] for r in PROJECT_RULES],
        'has_stock': stock,
    }

shiye = []
_manual_kws = [k for _, _, kws, _ in PROJECT_RULES for k in kws]
for proj, ptype, kws, text_scan in PROJECT_RULES:
    members = [n for n in src['nodes'] if any(k in (n.get('label') or '') for k in kws)]
    text_hits = _text_hits(kws) if text_scan else None
    if members or text_hits:
        shiye.append(_shiye_record(proj, ptype, members, text_hits=text_hits))

# ── auto-detect enterprises: ORG by industry suffix + linked 股本/股票 txn (or活跃度) ──
ENTERPRISE_SUFFIX = ('纱厂', '纺织', '公司', '银行', '银号', '钱庄', '铁矿', '煤矿', '矿务',
                     '矿', '工厂', '实业', '轮船', '电气', '电灯', '水泥', '面粉', '制造', '工程', '盐垦')
FINANCE_SUFFIX = ('银行', '银号', '钱庄')
STOCK_KW = ('股本', '股分', '股份', '股东', '股票', '股息', '官利', '红利', '认股', '增资', '股利', '董事')
org_groups = defaultdict(list)
for n in src['nodes']:
    lbl = n.get('label') or ''
    if n.get('entity_type') == '团体' and any(s in lbl for s in ENTERPRISE_SUFFIX):
        org_groups[lbl].append(n)
auto = []
for lbl, grp in org_groups.items():
    if any(k in lbl for k in _manual_kws):     # already covered by a manual rule
        continue
    members = list(grp); has_stock = False; ntxn = 0; deg = 0
    for n in grp:
        for direction, e in edges_by_node.get(n['id'], []):
            deg += 1
            on = nodes_by_id.get(e['target'] if direction == 'out' else e['source'], {})
            ev = (e.get('metadata') or {}).get('evidence_text', '') or ''
            if any(k in ev for k in STOCK_KW):
                has_stock = True
            if on.get('entity_type') == '交易':
                members.append(on); ntxn += 1
                if any(k in (on.get('label') or '') for k in STOCK_KW):
                    has_stock = True
    if not (has_stock or ntxn >= 2 or deg >= 8):
        continue
    ptype = '金融' if any(s in lbl for s in FINANCE_SUFFIX) else '实业'
    auto.append(_shiye_record(lbl, ptype, members, stock=has_stock))
auto.sort(key=lambda s: (-(1 if s['has_stock'] else 0), -s['member_count']))
shiye.extend(auto[:40])                          # cap to keep tab usable
shiye.sort(key=lambda s: -s['member_count'])
(out_dir / 'shiye.json').write_text(json.dumps(shiye, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'wrote {len(shiye)} 事业 projects ({len(auto[:40])} auto-detected enterprises, '
      f'{sum(1 for s in auto[:40] if s["has_stock"])} with 股本/股票)')

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
}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
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

# Topic 8: 安徽同乡圈 — 单一真相源 = renshi 的 anhui_classify (0616 第5波① 补全后刷新)
_AH_SRC_LABEL = {'statement': '籍贯陈述', 'tongxianghui': '同乡会会籍', 'tongxiang_event': '同乡会同席',
                 'gazetteer': '考订名录', 'kinship': '亲属推断', 'keyword': '地名线索'}
_AH_SRC_COLOR = {'statement': '#1b7837', 'tongxianghui': '#d94801', 'tongxiang_event': '#d94801',
                 'gazetteer': '#6a51a3', 'kinship': '#a35c1a', 'keyword': '#8c8c8c'}
anhui_persons = sorted((r for r in renshi if r.get('is_anhui')),
                       key=lambda r: -(r.get('interactions') or 0))
_ah_src_counts = Counter(r.get('anhui_source') for r in anhui_persons)
s8_items = []
for p in anhui_persons:
    src_k = p.get('anhui_source') or 'keyword'
    badge = (f'<span style="background:{_AH_SRC_COLOR.get(src_k, "#888")}22;color:{_AH_SRC_COLOR.get(src_k, "#888")};'
             f'border:1px solid {_AH_SRC_COLOR.get(src_k, "#888")}55;border-radius:9px;padding:0 7px;font-size:11px">'
             f'{_AH_SRC_LABEL.get(src_k, src_k)}</span>')
    jg = f' <span style="color:#9b2926;font-size:11px">{esc(p["jiguan"])}</span>' if p.get('jiguan') else ''
    s8_items.append(f'<strong>{esc(p["label"])}</strong>{jg} {badge} '
                    f'<span style="color:#bbada0;font-size:11px">互动{p.get("interactions", 0)}</span>')
_ah_breakdown = '、'.join(f'{_AH_SRC_LABEL.get(k, k)} {v}' for k, v in _ah_src_counts.most_common())
special8_html = render_special(
    '安徽同乡圈（皖籍人物清单）',
    f'徐乃昌祖籍南陵。经分级判定（籍贯陈述 &gt; 同乡会会籍/同席 &gt; 考订名录 &gt; 亲属推断 &gt; 地名线索）'
    f'共 {len(anhui_persons)} 位皖籍人物，按与徐互动次数排序。来源构成：{_ah_breakdown}。'
    f'其中“同乡会同席”为本轮（0616）新增——凡与徐同赴皖省/徽宁/安徽旅沪同乡会者皆判为皖籍。无重新抽取。',
    [{'title': f'皖籍人物（{len(anhui_persons)}）', 'items': s8_items}]
)
(specials_dir / 'anhui-network.html').write_text(special8_html, encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# FIGURES (S5/S6) — standalone print-static paper figures. No re-extraction.
# Data drawn from renshi (籍贯/亲属), shiye (事业 agents, S1-canonicalized), kin
# edges, and per-person 地 edges. Mirrors 《王世杰日记》3.1 (关系) / 3.2 (行迹).
# ════════════════════════════════════════════════════════════════════════════
XU = next(iter(xu_ids), None)
xu_primary = redirect(XU) if XU else None

# 1-hop kin of 徐乃昌 = the "family" set (for ring 1 + family trajectory)
family = {}
for ke in kin_edges_out:
    s, t = redirect(ke['source']), redirect(ke['target'])
    if s == xu_primary and t != xu_primary:
        family.setdefault(t, {'label': ke.get('target_label'), 'kin_type': ke.get('kin_type')})
    elif t == xu_primary and s != xu_primary:
        family.setdefault(s, {'label': ke.get('source_label'), 'kin_type': ke.get('kin_type')})

# ── Figure 1: concentric relationship rings ──────────────────────────────────
# ring 0 徐乃昌 · 1 亲属 · 2 南陵同乡 · 3 安徽同乡 · 4 其他 (high-interaction only)
RING_LABELS = {0: '徐乃昌', 1: '亲属', 2: '南陵同乡', 3: '安徽同乡', 4: '其他'}
RING_CAP = {1: 200, 2: 200, 3: 80, 4: 40}     # per-ring cap for figure legibility


# people connected to 南陵-area places (hometown circle) — widens the thin 南陵 tier
# beyond the few with an explicit 籍贯 statement.
_nanling_loc_ids = {nid for nid, n in locs.items() if resolve_city(n.get('label')) == '南陵'}
_nanling_persons = set()
for _e in src['edges']:
    _s, _t = _e.get('source'), _e.get('target')
    if _t in _nanling_loc_ids and nodes_by_id.get(_s, {}).get('entity_type') == '人':
        _nanling_persons.add(redirect(_s))
    if _s in _nanling_loc_ids and nodes_by_id.get(_t, {}).get('entity_type') == '人':
        _nanling_persons.add(redirect(_t))
_nanling_persons.discard(xu_primary)

# ── 互动频次 with 徐乃昌 (0616 第5波④: 圆点大小按其与徐的互动频次) ──────────────────
# Direct person↔徐 relations (致书/赠/同席/亲属…) + co-attendance hyperedges that include 徐.
# This is closeness-to-ego, distinct from a person's TOTAL interactions (which also count
# their ties to third parties). Drives the dot radius so the rings read as 亲疏 by 与徐互动.
xu_freq = Counter()
for _e in per_edges_deduped:
    _a, _b = _e.get('source'), _e.get('target')
    if _a == xu_primary and _b:
        xu_freq[_b] += 1
    elif _b == xu_primary and _a:
        xu_freq[_a] += 1
for _h in src.get('hyperedges', []):
    _mem = {redirect(m) for m in (_h.get('nodes') or [])
            if nodes_by_id.get(m, {}).get('entity_type') == '人'}
    if xu_primary in _mem:
        for _m in _mem:
            if _m != xu_primary:
                xu_freq[_m] += 1


def _ring_of(r):
    if r['id'] == xu_primary:
        return 0
    if r['id'] in family:
        return 1
    jg = r.get('jiguan') or ''
    if '南陵' in jg or jg == '宛陵' or r['id'] in _nanling_persons:
        return 2
    if r.get('is_anhui'):
        return 3
    return 4


_ring_pool = defaultdict(list)
for r in renshi:
    if r['id'] == xu_primary:
        continue
    ring = _ring_of(r)
    _ring_pool[ring].append({
        'id': r['id'], 'label': r['label'], 'ring': ring,
        'interactions': r.get('interactions') or 0,
        'xu_freq': xu_freq.get(r['id'], 0),            # 与徐互动频次 → 圆点大小
        'kin_type': family.get(r['id'], {}).get('kin_type'),
        'jiguan': r.get('jiguan'),
        'anhui_source': r.get('anhui_source'),
    })
rings = []
for ring, pool in _ring_pool.items():
    # outer rings are capped for legibility — keep those CLOSEST to 徐 (by 与徐互动频次)
    pool.sort(key=lambda x: (-x['xu_freq'], -x['interactions']))
    rings.extend(pool[:RING_CAP.get(ring, 200)])
ring_counts = {RING_LABELS[k]: len(_ring_pool[k]) for k in sorted(_ring_pool)}
(out_dir / 'relationship_rings.json').write_text(
    json.dumps(rings, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── Figure 2: 事业 clusters (person ↔ project, overlap highlighted) ───────────
TYPE_COLOR = {'编纂': '#6a51a3', '著述': '#9e6ebd', '实业': '#2171b5', '金融': '#08519c',
              '垦务': '#238b45', '赈务': '#cb181d', '社团': '#d94801', '家族': '#8c510a',
              '金石收藏': '#1b7837', '诗词文会': '#c51b7d'}
clu_projects = []
person_projects = defaultdict(list)
for s in shiye:
    ags = sorted({canonicalize_person(a) for a in (s.get('agents') or []) if a and a != '徐乃昌'})
    if len(ags) < 2:
        continue
    ags = ags[:30]
    clu_projects.append({'project': s['project'], 'type': s.get('type'),
                         'persons': ags, 'member_count': s.get('member_count')})
    for a in ags:
        person_projects[a].append(s['project'])
clu_projects = sorted(clu_projects, key=lambda c: -len(c['persons']))[:24]
_kept = {c['project'] for c in clu_projects}
overlap = {p: [pr for pr in prjs if pr in _kept]
           for p, prjs in person_projects.items() if sum(pr in _kept for pr in prjs) >= 2}
clusters = {'projects': clu_projects, 'overlap': overlap}
(out_dir / 'shiye_clusters.json').write_text(
    json.dumps(clusters, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── Figure 3: 行迹 geo heatmap (徐乃昌 + family) ──────────────────────────────
# 第2波 feedback: weight by DISTINCT DAYS (天数), not mention count; 南陵/芜湖 must
# show (family trips count). Aggregate per place; intensity = unique dates that 徐 OR
# a family member was recorded there. Family-event days in 南陵 (祭祖/扫墓/分租/原籍)
# are folded in so 妻女代行 trips register even without a 地 edge.
_place_meta = {}   # place -> {lat,lng, xu_days:set, fam_days:set, persons:Counter}


def _place_entry(key, coord):
    return _place_meta.setdefault(key, {'lat': coord[0], 'lng': coord[1],
                                        'xu_days': set(), 'fam_days': set(), 'persons': Counter()})


def _collect_place_days(label, id_set, is_xu):
    for pid in id_set:
        for direction, e in edges_by_node.get(pid, []):
            if direction != 'out' or e.get('relation') not in ('拜访', '位于'):
                continue
            tn = nodes_by_id.get(e['target'], {})
            if tn.get('entity_type') != '地':
                continue
            lbl = tn.get('label')
            city = resolve_city(lbl)
            coord = COORDS.get(city) if city else VENUE_COORDS.get(lbl)
            if not coord:
                continue
            d = e.get('source_location') or tn.get('captured_at')
            m = _place_entry(city or lbl, coord)
            if d:
                (m['xu_days'] if is_xu else m['fam_days']).add(d)
            m['persons'][label] += 1


_collect_place_days('徐乃昌', set(primary_orig_ids.get(xu_primary, [])) | set(xu_ids), True)
for _pid, _info in family.items():
    _collect_place_days(_info.get('label') or _pid, set(primary_orig_ids.get(_pid, [_pid])), False)

# Fold 家族事务 南陵 timeline days into 南陵 family-days (祭祖/扫墓/分租/原籍 — 妻女代行,
# often no 地 edge). These are the days the user means by "南陵应该不止一次（包括妻女）".
_NANLING = COORDS['南陵']
_nl = _place_entry('南陵', _NANLING)
for _s in shiye:
    if _s.get('project') == '家族事务':
        for _h in _s.get('timeline') or []:
            # physical-hometown markers only (avoid bare 族/分租 that may happen elsewhere)
            if any(k in (_h.get('snippet') or '') for k in ('南陵', '原籍', '祠堂', '祖茔', '扫墓', '祭祖', '回里', '返里', '归里')):
                _nl['fam_days'].add(_h['date'])

trajectory = []
for k, m in _place_meta.items():
    alld = m['xu_days'] | m['fam_days']
    if not alld:
        continue
    trajectory.append({
        'place': k, 'lat': m['lat'], 'lng': m['lng'],
        'days': len(alld), 'days_xu': len(m['xu_days']), 'days_family': len(m['fam_days']),
        'persons': [p for p, _ in m['persons'].most_common(8)],
    })
trajectory.sort(key=lambda t: -t['days'])
(out_dir / 'trajectory.json').write_text(
    json.dumps(trajectory, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── Figure 0 data: 人物同现总图 (paper §3.1 fig4 style) ───────────────────────
# ONE network summarizing the whole cast. Exclude the ego (徐乃昌, degree 7000+) so
# modules around 吴舜臣(账单)/陈乃乾·李拔可(藏书)/赈灾 emerge instead of a star.
# Edges = extracted person↔person relations (致书/同席/亲属/赠…) + 同席 hyperedge
# co-attendance pairs (both restricted to non-ego). Diary is terse, so real
# relations give a denser, cleaner network than raw same-day co-occurrence.
from itertools import combinations as _combos
_pair_w = Counter()
for _e in per_edges_deduped:                          # deduped person↔person relations
    _a, _b = _e.get('source'), _e.get('target')
    if _a and _b and _a != _b and _a != xu_primary and _b != xu_primary:
        _pair_w[tuple(sorted((_a, _b)))] += 1
for _h in src.get('hyperedges', []):                  # 同席/共谋 co-attendance
    _mem = sorted({redirect(m) for m in (_h.get('nodes') or [])
                   if nodes_by_id.get(m, {}).get('entity_type') == '人'})
    _mem = [m for m in _mem if m != xu_primary]
    if 2 <= len(_mem) <= 14:
        for _a, _b in _combos(_mem, 2):
            _pair_w[(_a, _b)] += 1
_wdeg = Counter()
for (_a, _b), _w in _pair_w.items():
    _wdeg[_a] += _w
    _wdeg[_b] += _w
OVERVIEW_TOPN = 100        # 0616 第5波③: 缩到最密切的 100 人 (was 240) → 圈层结构更清晰
_top_ids = {i for i, _ in _wdeg.most_common(OVERVIEW_TOPN)}
ov_edges = [{'s': a, 't': b, 'w': w} for (a, b), w in _pair_w.items()
            if a in _top_ids and b in _top_ids]
# detect modules ON the overview subgraph (existing global community is degenerate
# here). Deterministic weighted label-propagation → colored clusters like paper fig4.
_ov_adj = defaultdict(list)
for _e in ov_edges:
    _ov_adj[_e['s']].append((_e['t'], _e['w']))
    _ov_adj[_e['t']].append((_e['s'], _e['w']))
_lab = {i: i for i in _top_ids}
for _it in range(12):
    _changed = 0
    for i in sorted(_top_ids):
        if not _ov_adj[i]:
            continue
        _c = Counter()
        for j, w in _ov_adj[i]:
            _c[_lab[j]] += w
        _mx = max(_c.values())
        _best = min(L for L, cc in _c.items() if cc == _mx)   # deterministic tie-break
        if _lab[i] != _best:
            _lab[i] = _best
            _changed += 1
    if not _changed:
        break
_sizes = Counter(_lab.values())
_renum = {L: idx for idx, (L, _) in enumerate(_sizes.most_common())}   # big modules first
_comm_of = {i: (_renum[_lab[i]] if _sizes[_lab[i]] >= 3 else -1) for i in _top_ids}
ov_nodes = [{'id': i, 'label': nodes_by_id.get(i, {}).get('label') or i,
             'deg': _wdeg[i], 'community': _comm_of.get(i, -1)} for i in _top_ids]

# ── auto-name each module (说明 cluster 逻辑, 0616 第5波③) ──────────────────────
# A module = a set of people who co-appear with each other far more than with outsiders
# (weighted label-propagation). Name it by theme if a known anchor-set hits, else by its
# two highest-degree members. Legend lists name·size·代表人物 so the clustering is legible.
def _lbl(i):
    return nodes_by_id.get(i, {}).get('label') or i
_THEME = [
    ('藏书·刻书圈', {'陈乃乾', '金颂清', '李拔可', '缪荃孙', '刘翰怡', '张元济', '张菊生', '叶遐庵',
                    '傅增湘', '傅沅叔(增湘)', '董康', '罗子经', '杨寿祺', '宗子戴', '王富晋'}),
    ('实业·金融圈', {'吴寄尘', '刘晦之', '张孝若', '周美权', '陈一甫', '陈西甫', '聂云台', '徐静仁'}),
    ('同乡·赈务圈', {'夏辅宜', '江彤侯', '王揖唐', '胡朴安', '程演生', '余寿平', '洪希甫', '江汉珊'}),
    ('金石·遗老圈', {'郑文焯', '况周颐', '况夔笙', '朱祖谋', '周梦坡', '邹安', '邹寿祺', '狄楚青'}),
    ('收租·南陵圈', {'吴舜臣', '舜臣', '牧子襄', '陈海汇', '盛彝斋', '杨芷青'}),
    ('医药圈', {'鲍承良', '丁仲祜', '丁仲枯', '余伯陶', '杨赤城'}),
]
_comm_members = defaultdict(list)
for i in _top_ids:
    cm = _comm_of.get(i, -1)
    if cm >= 0:
        _comm_members[cm].append(i)
ov_comms = []
for cm, ids in _comm_members.items():
    ids.sort(key=lambda i: -_wdeg[i])
    labels = [_lbl(i) for i in ids]
    lset = set(labels)
    # theme only when ≥2 of its anchors sit in THIS module (else a lone 藏书 person would
    # mislabel an实业 cluster); pick the theme with the strongest overlap → distinct per module.
    _cand = [(len(anc & lset), nm) for nm, anc in _THEME if len(anc & lset) >= 2]
    theme = max(_cand)[1] if _cand else None
    base = f'{labels[0]}·{labels[1]}' if len(labels) >= 2 else labels[0]
    name = f'{base}（{theme}）' if theme else f'{base} 等'
    ov_comms.append({'community': cm, 'name': name, 'size': len(ids),
                     'theme': theme, 'top': labels[:6]})
ov_comms.sort(key=lambda c: -c['size'])
overview_graph = {'nodes': ov_nodes, 'edges': ov_edges, 'unique_total': per_unique,
                  'shown': len(ov_nodes), 'communities': ov_comms}
(out_dir / 'cooccurrence_overview.json').write_text(
    json.dumps(overview_graph, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── 第3波 ①: 事件性质五分类 (按天·可多标签, no re-extraction) ──────────────────
# Keywords tuned for PRECISION (it's a published count): markers that signal the
# event-nature itself, not incidental mentions. Notably 诗词文会 uses gathering/
# composition markers (NOT bare 诗/词 — those match book titles 《…诗》 = 收藏); 遗民
# excludes bare 宣统/德宗 (reign-years in land deeds/genealogies are not 遗民活动).
NATURE_RULES = [
    ('金石收藏', ['碑帖', '法帖', '字帖', '丛帖', '碑版', '拓本', '墨拓', '钟鼎', '彝器',
                 '古泉', '古玩', '金石', '法书', '名画', '书画', '造像', '墓志', '古砚',
                 '古印', '宋椠', '宋本', '元刊', '善本', '鉴藏', '鉴赏', '题跋', '收藏', '碑']),
    ('诗词文会', ['和韵', '次韵', '叠韵', '分韵', '文酒', '赋诗', '社集', '联句', '诗钟',
                 '征诗', '征题', '酬唱', '诗会', '词社', '吟社', '击钵', '雅会', '寿序',
                 '挽联', '楹联', '题襟']),
    ('遗民活动', ['遗老', '遗民', '逊清', '前清遗', '胜朝', '故国', '复辟', '宗社', '崇陵',
                 '谒陵', '祭陵', '孤臣', '清室', '优待条件', '逊国', '旧君', '逊位诏']),
    ('乡邦活动', ['同乡会', '会馆', '徽宁', '旅沪安徽', '南陵旅沪', '皖同乡', '修志', '南陵志',
                 '安徽通志', '通志局', '赈', '义振', '放赈', '急赈', '赈款', '桑梓', '乡邦',
                 '垦务', '万顷湖', '万春湖', '田产', '原籍', '祠堂', '祭祖', '扫墓', '族']),
]
nature_counts = Counter()
nature_year = defaultdict(lambda: Counter())
nature_samples = defaultdict(list)
_nat_total = 0
_nat_other = 0
for _d in sorted(_SRC_BODY):
    body = _SRC_BODY[_d]
    _nat_total += 1
    yr = _d[:4]
    hit_cats = []
    for cat, kws in NATURE_RULES:
        kw = next((k for k in kws if k in body), None)
        if kw:
            hit_cats.append(cat)
            nature_counts[cat] += 1
            nature_year[yr][cat] += 1
            if len(nature_samples[cat]) < 60:
                pos = body.find(kw)
                nature_samples[cat].append({
                    'date': _d, 'page': page_for(_d), 'kw': kw,
                    'snippet': body[max(0, pos - 8):pos + 24].replace('\n', ' ').strip()})
    if not hit_cats:
        _nat_other += 1
        nature_counts['其它'] += 1
        nature_year[yr]['其它'] += 1
        if len(nature_samples['其它']) < 60:
            nature_samples['其它'].append({'date': _d, 'page': page_for(_d), 'kw': '',
                                          'snippet': body[:28].replace('\n', ' ').strip()})
NATURE_ORDER = ['金石收藏', '诗词文会', '遗民活动', '乡邦活动', '其它']
event_nature = {
    'total_days': _nat_total,
    'counts': {c: nature_counts[c] for c in NATURE_ORDER},
    'note': '按天·可多标签：一天可同时计入多类，故各类之和大于总天数；其它=五类关键词均未命中。',
    'by_year': {y: {c: nature_year[y][c] for c in NATURE_ORDER if nature_year[y][c]}
                for y in sorted(nature_year)},
    'samples': {c: nature_samples[c] for c in NATURE_ORDER},
}
(out_dir / 'event_nature.json').write_text(
    json.dumps(event_nature, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── 新需求 (0605/0615) top10 事件类型: ~11-category daily activity classifier ─────
# Deterministic (no LLM, no re-extraction). Each of the 6134 day-entries gets every
# matching activity label; rank categories by distinct days. Keyword sets tuned for
# precision (it is a published figure). 购藏书籍 requires book-context tokens (not bare
# 购, which also buys 碑/古玩); 通信 deliberately omitted — it is a medium, not an activity.
ACTIVITY_RULES = [
    ('收租稻务', ['收租', '租稻', '稻租', '售稻', '卖稻', '收稻', '每石', '佃户', '佃', '完粮',
                 '押板', '稻洋', '田租', '租息', '租簿', '期稻', '稻价', '稻款', '租洋', '业户']),
    ('金石碑帖', ['碑帖', '法帖', '字帖', '丛帖', '碑版', '拓本', '墨拓', '钟鼎', '彝器', '古泉',
                 '古玩', '金石', '法书', '名画', '书画', '造像', '墓志', '古砚', '古印', '宋椠',
                 '鉴藏', '鉴赏', '题跋', '拓片', '碑', '法帖']),
    ('编纂著述', ['修志', '通志', '县志', '南陵志', '志稿', '志书', '志馆', '通志局', '编纂',
                 '纂修', '校勘', '校刊', '刻书', '付印', '排印', '撰', '谱牒', '族谱', '家谱', '刊印']),
    ('购藏书籍', ['取书', '书价', '书肆', '书店', '来青阁', '蟬隐庐', '收书', '买书', '售书',
                 '书贾', '书目', '旧书', '宋本', '元刊', '善本', '刻本', '钞本', '抄本', '书估']),
    ('赈务善举', ['赈', '义振', '放赈', '急赈', '工赈', '赈款', '水灾', '旱灾', '灾民', '捐助',
                 '义振', '红十字', '育婴', '义学', '平籴', '施药', '善举', '募捐', '助振']),
    ('家族事务', ['三太太', '大太太', '太太', '宗祠', '祠堂', '祭祖', '扫墓', '祖茔', '原籍',
                 '分租', '分家', '丧', '葬', '殓', '弟妇', '家事', '族产', '族人', '修谱', '过继']),
    ('社交宴游', ['招饮', '侑觞', '雅集', '社集', '祝寿', '寿筵', '答拜', '会饮', '酒叙', '宴',
                 '小酌', '茶话', '饯', '谭', '晤', '过访', '叙谈']),
    ('医药疾病', ['延医', '诊方', '服药', '病', '热度', '感冒', '春温', '疾', '痊愈', '去世',
                 '卒', '逝', '疫', '咳', '痰', '医治', '配药', '抱恙']),
    ('佛事宗教', ['佛经', '诵经', '念佛', '礼佛', '佛事', '佛像', '放生', '善书', '礼忏', '观音',
                 '弥陀', '金刚经', '法师', '皈依', '功德', '菩萨', '诵经', '写经', '印经']),
    # 斋/道人/寺 dropped: 斋=书斋/斋号(室名), 道人=人名(潜道人), 寺=访寺多为社交/游观 — over-count.
    ('政治时局', ['党部', '知事', '县长', '附加税', '库券', '公债', '戒严', '土匪', '绑匪',
                 '保卫团', '自卫团', '民团', '省署', '县署', '兵变', '军阀', '减租', '陈报']),
    ('金融实业', ['银行', '钱庄', '支票', '存款', '保险箱', '股本', '股票', '股息', '汇兑',
                 '实业公司', '矿', '票号', '洋行', '盐垦', '电灯公司', '碾米厂']),
]
activity_counts = Counter()
activity_year = defaultdict(lambda: Counter())
activity_samples = defaultdict(list)
_day_cats = {}                                   # date -> set(cats) — reused by 吴舜臣 dossier
for _d in sorted(_SRC_BODY):
    body = _SRC_BODY[_d]
    cats = set()
    for cat, kws in ACTIVITY_RULES:
        kw = next((k for k in kws if k in body), None)
        if kw:
            cats.add(cat)
            activity_counts[cat] += 1
            activity_year[_d[:4]][cat] += 1
            if len(activity_samples[cat]) < 50:
                pos = body.find(kw)
                activity_samples[cat].append({
                    'date': _d, 'page': page_for(_d), 'kw': kw,
                    'snippet': body[max(0, pos - 8):pos + 26].replace('\n', ' ').strip()})
    _day_cats[_d] = cats
activity_ranked = activity_counts.most_common()
activity_types = {
    'total_days': len(_SRC_BODY),
    'ranked': [{'cat': c, 'days': n, 'rank': i + 1} for i, (c, n) in enumerate(activity_ranked)],
    'top10': [c for c, _ in activity_ranked[:10]],
    'by_year': {y: dict(activity_year[y]) for y in sorted(activity_year)},
    'samples': {c: activity_samples[c] for c, _ in activity_ranked},
    'note': '按天·可多标签：一天可归入多类；排名按命中天数。确定性关键词分类，无 LLM、无重新抽取。',
}
(out_dir / 'activity_types.json').write_text(
    json.dumps(activity_types, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('  top10 事件类型: ' + ' / '.join(f'{c}{n}' for c, n in activity_ranked[:10]))

# ── 新需求 (0615) 吴舜臣 dossier: per-month activity timeline vs user ground truth ─
# All 舜臣 (舜臣/舜老/吴舜臣) mention-days, classified by activity (_day_cats) with the
# 舜-sentence as snippet, grouped by 年-月. Header compares against the user's manual
# per-year 频次 count (图谱改进0615.xlsx 吴舜臣 sheet) so completeness is auditable.
WU_TRUTH_BY_YEAR = {1920: 54, 1921: 62, 1922: 102, 1923: 60, 1924: 90, 1925: 60,
                    1926: 69, 1927: 63, 1928: 71, 1929: 46, 1930: 55, 1931: 56,
                    1932: 48, 1933: 39, 1934: 48, 1935: 21, 1936: 23, 1937: 33, 1938: 11}
_wu_acct_days = defaultdict(set)
_wu_acct_rows = Counter()
for _t in txns:
    if _t.get('agent') == '吴舜臣' and _t.get('date'):
        _wu_acct_days[_t['date'][:4]].add(_t['date'])
        _wu_acct_rows[_t['date'][:4]] += 1
_wu_months = defaultdict(lambda: {'days': 0, 'cats': Counter(), 'snips': []})
_wu_mention_days = defaultdict(int)
for _d in sorted(_SRC_BODY):
    body = _SRC_BODY[_d]
    if not any(a in body for a in _SHUN):
        continue
    _wu_mention_days[_d[:4]] += 1
    ym = _d[:7]
    _m = _wu_months[ym]
    _m['days'] += 1
    for c in _day_cats.get(_d, ()):
        _m['cats'][c] += 1
    _sent = next((s.strip() for s in re.split(r'[。\n/]', body) if any(a in s for a in _SHUN)), '')
    if _sent and len(_m['snips']) < 6:
        _m['snips'].append({'date': _d, 'page': page_for(_d), 'text': _sent[:80]})
wu_dossier = {
    'by_year': [{'year': y, 'truth': WU_TRUTH_BY_YEAR.get(y, 0),
                 'mention_days': _wu_mention_days.get(str(y), 0),
                 'acct_days': len(_wu_acct_days.get(str(y), ())),
                 'acct_rows': _wu_acct_rows.get(str(y), 0)} for y in range(1920, 1939)],
    'months': [{'ym': ym, 'days': v['days'],
                'cats': [c for c, _ in v['cats'].most_common()], 'snips': v['snips']}
               for ym, v in sorted(_wu_months.items())],
    'totals': {'truth': sum(WU_TRUTH_BY_YEAR.values()),
               'mention_days': sum(_wu_mention_days.values()),
               'acct_days': sum(len(s) for s in _wu_acct_days.values()),
               'acct_rows': sum(_wu_acct_rows.values())},
}
(out_dir / 'wu_shunchen.json').write_text(
    json.dumps(wu_dossier, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'  吴舜臣 dossier: {len(wu_dossier["months"])} months, mention-days '
      f'{wu_dossier["totals"]["mention_days"]}, 账单 {wu_dossier["totals"]["acct_rows"]} '
      f'rows (truth {wu_dossier["totals"]["truth"]})')

# people-circles from 金石收藏 / 诗词文会 days → feed the 事业 cluster ("古玩收藏的一群人")
_nat_day_people = defaultdict(Counter)        # cat -> Counter(primary_pid -> #days)
for _n in src['nodes']:
    if _n.get('entity_type') != '人':
        continue
    _d = _n.get('captured_at')
    if not _d:
        continue
    body = _SRC_BODY.get(_d, '')
    _p = redirect(_n['id'])
    if _p == xu_primary:
        continue
    for cat in ('金石收藏', '诗词文会'):
        kws = dict(NATURE_RULES)[cat]
        if any(k in body for k in kws):
            _nat_day_people[cat][_p] += 1
for cat in ('金石收藏', '诗词文会'):
    ppl = sorted((nodes_by_id.get(pid, {}).get('label') for pid, c in _nat_day_people[cat].items() if c >= 4),
                 key=lambda x: x or '')
    ppl = [p for p in ppl if p][:30]
    if len(ppl) >= 2:
        clu_projects.append({'project': cat, 'type': '金融' if False else cat,
                             'persons': ppl, 'member_count': len(ppl)})
        for a in ppl:
            person_projects[a].append(cat)
# recompute overlap with the two new circles included
_kept = {c['project'] for c in clu_projects}
overlap = {p: [pr for pr in prjs if pr in _kept]
           for p, prjs in person_projects.items() if sum(pr in _kept for pr in prjs) >= 2}
clusters = {'projects': clu_projects, 'overlap': overlap}
(out_dir / 'shiye_clusters.json').write_text(
    json.dumps(clusters, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# ── emit the standalone HTML figure pages ────────────────────────────────────
FIG_CSS = """
*{box-sizing:border-box} body{margin:0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
background:#faf8f4;color:#2b2622} .wrap{max-width:1080px;margin:0 auto;padding:18px}
nav a{color:#9b2926;text-decoration:none;margin-right:14px;font-size:13px}
h1{font-size:21px;margin:10px 0 4px} .lede{color:#6b635a;font-size:13px;margin-bottom:14px;line-height:1.6}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0;font-size:12px}
.legend span{display:inline-flex;align-items:center;gap:5px}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
.card{background:#fff;border:1px solid #e7e0d6;border-radius:8px;padding:8px}
.foot{color:#a89f93;font-size:11px;margin-top:10px}
"""

_fig_nav = ('<nav><a href="../index.html">← 返回总览</a>'
            '<a href="people-overview.html">人物同现总图</a>'
            '<a href="relationship-rings.html">关系同心圆</a>'
            '<a href="organizations.html">团体Top10</a>'
            '<a href="shiye-clusters.html">事业聚合</a>'
            '<a href="event-nature.html">事件性质</a>'
            '<a href="trajectory-heatmap.html">行迹热力图</a>'
            '<a href="event-types.html">事件类型Top10</a>'
            '<a href="wu-shunchen.html">吴舜臣活动谱</a>'
            '<a href="nanling-gazetteer.html">南陵县志长编</a></nav>')


def _fig_page(title, lede, body, head_extra=''):
    return (f'<!doctype html><html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link rel="icon" href="../favicon.svg">'
            f'<title>{esc(title)} · 徐乃昌日记 KG</title><style>{FIG_CSS}</style>{head_extra}'
            f'</head><body><div class="wrap">{_fig_nav}<h1>{esc(title)}</h1>'
            f'<div class="lede">{lede}</div>{body}'
            f'<div class="foot">数据驱动 · 无重新抽取 · 由 build_views.py 生成</div></div></body></html>')


# Figure 0 — 人物同现总图 (co-occurrence overview, Cytoscape, paper §3.1 fig4 style)
_COMM_PALETTE = ['#9b2926', '#2171b5', '#238b45', '#6a51a3', '#d94801', '#1b7837',
                 '#c51b7d', '#08519c', '#8c510a', '#525252', '#a6761d', '#386cb0']
_f0_body = f"""
<div class="legend">
 <span>共 <b style="color:#9b2926;font-size:15px">{overview_graph['unique_total']}</b> 位 unique 人物（已按本名/字/号合并去重）</span>
 <span style="color:#888">本图为与徐乃昌最密切的 <b>{overview_graph['shown']}</b> 人；已隐去徐本人(与所有人相连)，让圈子结构显现</span>
</div>
<div class="card" style="padding:12px 14px">
 <div style="font-size:13px;font-weight:700;margin-bottom:4px">圈子（cluster）怎么分出来的</div>
 <div style="font-size:12px;color:#5a5247;line-height:1.7">
  连线 = 两人“同现”（同一天同框 / 同席 / 直接往来）。算法对这 {overview_graph['shown']} 人做<b>加权标签传播</b>
  （weighted label propagation，确定性、可复现）：每人反复改取“邻居里同现权重之和最大”的标签，直到稳定，
  于是<b>彼此同现远多于与外人同现</b>的人自动聚成同一色块。下方每个色块即一个圈子，命中已知主题者直接命名，
  其余以两位核心人物代称。点节点高亮其邻里。
 </div>
 <div id="cl" style="margin-top:8px"></div>
</div>
<div class="card"><div id="cy" style="height:720px"></div></div>
<script src="https://unpkg.com/cytoscape@3/dist/cytoscape.min.js"></script>
<script>
const G={json.dumps(overview_graph,ensure_ascii=False)};
const PAL={json.dumps(_COMM_PALETTE)};
const col=c=>c<0?'#bbb':PAL[((c%PAL.length)+PAL.length)%PAL.length];
document.getElementById('cl').innerHTML=(G.communities||[]).map(m=>
 `<div style="display:inline-block;vertical-align:top;margin:4px 10px 4px 0;max-width:220px">
   <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${{col(m.community)}};margin-right:5px"></span>
   <b style="font-size:12px">${{m.name}}</b> <span style="color:#bbada0;font-size:11px">${{m.size}}人</span>
   <div style="font-size:11px;color:#888;margin-left:15px">${{m.top.join('、')}}</div></div>`).join('');
const els=[];
G.nodes.forEach(n=>els.push({{data:{{id:n.id,label:n.label,deg:n.deg,c:col(n.community)}}}}));
G.edges.forEach(e=>els.push({{data:{{source:e.s,target:e.t,w:e.w}}}}));
const cy=cytoscape({{container:document.getElementById('cy'),elements:els,
 style:[
  {{selector:'node',style:{{'background-color':'data(c)','label':'data(label)','font-size':'mapData(deg,2,300,7,16)',
    'width':'mapData(deg,2,300,8,52)','height':'mapData(deg,2,300,8,52)','color':'#33302b',
    'text-valign':'center','text-halign':'center','text-margin-y':-2,'min-zoomed-font-size':8}}}},
  {{selector:'edge',style:{{'width':'mapData(w,2,30,0.5,4)','line-color':'#d3ccc0','opacity':0.5,'curve-style':'haystack'}}}}
 ],
 layout:{{name:'cose',animate:false,nodeRepulsion:14000,idealEdgeLength:60,gravity:0.3,padding:24,componentSpacing:80}}}});
cy.on('tap','node',e=>{{const id=e.target.id();
 cy.elements().style('opacity',0.12);
 e.target.style('opacity',1);e.target.connectedEdges().style('opacity',0.7);
 e.target.neighborhood('node').style('opacity',1);}});
cy.on('tap',e=>{{if(e.target===cy)cy.elements().style('opacity',1);}});
</script>"""
(specials_dir / 'people-overview.html').write_text(_fig_page(
    '人物同现总图（最密切的100人）',
    f'仿《王世杰日记》图4。全库 {overview_graph["unique_total"]} 位人物中，取与徐乃昌同现最密的 '
    f'{overview_graph["shown"]} 人成网：同框即连线，加权标签传播自动分出藏书·实业·同乡·金石·收租等圈子'
    f'（共 {len(overview_graph["communities"])} 个，见上方图例与说明）。点击任一节点高亮其邻里。',
    _f0_body), encoding='utf-8')

# Figure: 事件性质五分类 (bars + per-category browse)
_en_body = f"""
<div id="bars" class="card" style="padding:14px"></div>
<div style="margin-top:12px" class="card" id="browse"></div>
<script>
const EN={json.dumps(event_nature,ensure_ascii=False)};
const ORDER=['金石收藏','诗词文会','遗民活动','乡邦活动','其它'];
const CC={{'金石收藏':'#1b7837','诗词文会':'#c51b7d','遗民活动':'#6a51a3','乡邦活动':'#d94801','其它':'#9aa0a6'}};
const mx=Math.max(...ORDER.map(c=>EN.counts[c]||0),1);
document.getElementById('bars').innerHTML='<div style="font-size:12px;color:#888;margin-bottom:8px">共 '+EN.total_days+' 天日记。'+EN.note+'</div>'+
 ORDER.map(c=>{{const v=EN.counts[c]||0;return `<div style="display:flex;align-items:center;gap:8px;margin:5px 0">
  <div style="width:72px;font-size:13px">${{c}}</div>
  <div style="flex:1;background:#f0ece4;border-radius:3px"><div style="width:${{100*v/mx}}%;background:${{CC[c]}};height:18px;border-radius:3px"></div></div>
  <div style="width:90px;text-align:right;font-size:13px"><b>${{v}}</b> 天</div></div>`;}}).join('');
let cur='金石收藏';
function browse(){{
 const s=EN.samples[cur]||[];
 document.getElementById('browse').innerHTML=
  '<div style="margin-bottom:8px">'+ORDER.map(c=>`<button data-c="${{c}}" style="margin-right:6px;padding:4px 10px;border:1px solid #ddd;border-radius:3px;cursor:pointer;background:${{c===cur?CC[c]:'#fff'}};color:${{c===cur?'#fff':'#333'}}">${{c}}</button>`).join('')+'</div>'+
  '<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="color:#999"><th style="text-align:left">日期</th><th style="text-align:left">页</th><th style="text-align:left">命中</th><th style="text-align:left">原文片段</th></tr>'+
  s.map(r=>`<tr><td style="padding:3px 6px 3px 0;white-space:nowrap">${{r.date}}</td><td style="color:#999">${{r.page||''}}</td><td style="color:${{CC[cur]}}">${{r.kw||''}}</td><td style="color:#5a5247">${{r.snippet}}</td></tr>`).join('')+'</table>';
 document.querySelectorAll('#browse button').forEach(b=>b.onclick=()=>{{cur=b.dataset.c;browse();}});
}}
browse();
</script>"""
(specials_dir / 'event-nature.html').write_text(_fig_page(
    '日记事件性质分类',
    '按五类性质给每天日记打标签（金石收藏 / 诗词文会 / 遗民活动 / 乡邦活动 / 其它），并分别计数。'
    '一天可同时归入多类（如某日既访碑帖又赋诗）。下方可逐类浏览命中条目与原文片段。无重新抽取。',
    _en_body), encoding='utf-8')

# Figure — top10 事件类型 (deterministic activity classifier, 新需求 0605/0615)
_AT_PALETTE = {'收租稻务': '#9b2926', '金石碑帖': '#1b7837', '编纂著述': '#2171b5',
               '购藏书籍': '#6a51a3', '赈务善举': '#cb181d', '家族事务': '#8c510a',
               '社交宴游': '#d94801', '医药疾病': '#c51b7d', '佛事宗教': '#386cb0',
               '政治时局': '#525252', '金融实业': '#a6761d'}
_et_body = f"""
<div id="bars" class="card" style="padding:14px"></div>
<div style="margin-top:12px" class="card" id="browse"></div>
<script>
const AT={json.dumps(activity_types,ensure_ascii=False)};
const PAL={json.dumps(_AT_PALETTE,ensure_ascii=False)};
const ranked=AT.ranked, mx=Math.max(...ranked.map(r=>r.days),1);
document.getElementById('bars').innerHTML='<div style="font-size:12px;color:#888;margin-bottom:10px">共 '+AT.total_days+' 天日记。'+AT.note+' <b>加粗=top10</b>。</div>'+
 ranked.map(r=>{{const c=r.cat,v=r.days,top=r.rank<=10,col=PAL[c]||'#9aa0a6';return `<div style="display:flex;align-items:center;gap:8px;margin:5px 0">
  <div style="width:28px;text-align:right;color:#bbada0;font-size:12px">${{r.rank}}</div>
  <div style="width:84px;font-size:13px;font-weight:${{top?700:400}}">${{c}}</div>
  <div style="flex:1;background:#f0ece4;border-radius:3px"><div style="width:${{100*v/mx}}%;background:${{col}};height:18px;border-radius:3px;opacity:${{top?1:.5}}"></div></div>
  <div style="width:70px;text-align:right;font-size:13px;font-weight:${{top?700:400}}">${{v}} 天</div></div>`;}}).join('');
let cur=ranked[0].cat;
function browse(){{
 const s=AT.samples[cur]||[];
 document.getElementById('browse').innerHTML=
  '<div style="margin-bottom:8px;line-height:2">'+ranked.map(r=>`<button data-c="${{r.cat}}" style="margin:0 6px 4px 0;padding:4px 10px;border:1px solid #ddd;border-radius:3px;cursor:pointer;background:${{r.cat===cur?(PAL[r.cat]||'#666'):'#fff'}};color:${{r.cat===cur?'#fff':'#333'}}">${{r.cat}}</button>`).join('')+'</div>'+
  '<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="color:#999"><th style="text-align:left">日期</th><th style="text-align:left">页</th><th style="text-align:left">命中</th><th style="text-align:left">原文片段</th></tr>'+
  s.map(r=>`<tr><td style="padding:3px 6px 3px 0;white-space:nowrap">${{r.date}}</td><td style="color:#999">${{r.page||''}}</td><td style="color:${{PAL[cur]||'#666'}}">${{r.kw||''}}</td><td style="color:#5a5247">${{r.snippet}}</td></tr>`).join('')+'</table>';
 document.querySelectorAll('#browse button').forEach(b=>b.onclick=()=>{{cur=b.dataset.c;browse();}});
}}
browse();
</script>"""
(specials_dir / 'event-types.html').write_text(_fig_page(
    '徐乃昌生活事件类型 Top10',
    f'把全部 {len(_SRC_BODY)} 天日记按 11 类活动打标签（确定性关键词，可多标签，无 LLM、无重新抽取），'
    f'按命中天数排名。Top10：{" · ".join(activity_types["top10"])}。下方按类浏览命中原文。',
    _et_body), encoding='utf-8')

# Figure — 吴舜臣 dossier (per-month activity timeline vs ground truth, 新需求 0615)
_wu_body = f"""
<div class="card" id="yr" style="padding:14px"></div>
<div style="margin-top:12px" class="card" id="grid" style="padding:10px"></div>
<script>
const WU={json.dumps(wu_dossier,ensure_ascii=False)};
const PAL={json.dumps(_AT_PALETTE,ensure_ascii=False)};
const T=WU.totals;
let yr='<div style="font-size:12px;color:#888;margin-bottom:8px">三个口径：<b>你的频次</b>=人工检索全部提及（含修志/赈务/家事/病等非账目）；<b>提及天</b>=语料中出现舜臣/舜老的日数（无重抽上限）；<b>账单</b>=收租交易行（经办人=吴舜臣）。合计 你 '+T.truth+' · 提及天 '+T.mention_days+' · 账单 '+T.acct_rows+' 行/'+T.acct_days+' 天。</div>';
yr+='<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="color:#999;text-align:right"><th style="text-align:left">年</th><th>你的频次</th><th>我·提及天</th><th>我·账单天</th><th>我·账单行</th><th>账单/提及</th></tr>';
WU.by_year.forEach(r=>{{const pct=r.mention_days?Math.round(100*r.acct_days/r.mention_days):0;
 yr+=`<tr style="text-align:right"><td style="text-align:left">${{r.year}}</td><td>${{r.truth}}</td><td>${{r.mention_days}}</td><td>${{r.acct_days}}</td><td><b>${{r.acct_rows}}</b></td><td style="color:#999">${{pct}}%</td></tr>`;}});
yr+=`<tr style="text-align:right;border-top:2px solid #ddd;font-weight:700"><td style="text-align:left">合计</td><td>${{T.truth}}</td><td>${{T.mention_days}}</td><td>${{T.acct_days}}</td><td>${{T.acct_rows}}</td><td></td></tr></table>`;
document.getElementById('yr').innerHTML=yr;
// month grid
let g='<div style="font-size:12px;color:#888;margin-bottom:8px">逐月：舜臣提及天数 + 该月活动类型标签（点击展开原文片段）。可与 0615 表逐月对照。</div>';
WU.months.forEach((m,i)=>{{
 const tags=m.cats.map(c=>`<span style="display:inline-block;background:${{(PAL[c]||'#999')}}22;color:${{PAL[c]||'#666'}};border:1px solid ${{PAL[c]||'#ccc'}};border-radius:10px;padding:1px 7px;font-size:11px;margin:1px 3px 1px 0">${{c}}</span>`).join('');
 g+=`<div style="border-bottom:1px solid #f0ece4;padding:6px 0">
   <div style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
   <b style="display:inline-block;width:72px">${{m.ym}}</b><span style="color:#9b2926">${{m.days}} 天</span>　${{tags}}</div>
   <div style="display:none;margin:4px 0 4px 78px;font-size:12px;color:#5a5247">`+
   m.snips.map(s=>`<div>${{s.date}} <span style="color:#bbb">p${{s.page||'?'}}</span>　${{s.text}}</div>`).join('')+`</div></div>`;
}});
document.getElementById('grid').innerHTML=g;
</script>"""
(specials_dir / 'wu-shunchen.html').write_text(_fig_page(
    '吴舜臣 · 收租代理活动谱',
    f'徐乃昌南陵收租代理吴舜臣（舜臣/舜老）的逐月活动谱：{wu_dossier["totals"]["mention_days"]} 个提及天，'
    f'其中 {wu_dossier["totals"]["acct_rows"]} 条进入账单（经办人筛选，原 230 条）。'
    f'与《图谱改进0615》人工检索（{wu_dossier["totals"]["truth"]} 次）逐年/逐月对照，差额为非账目活动（修志/赈务/家事/医病）。',
    _wu_body), encoding='utf-8')

# ── Figure — Top10 团体 (organizations by recurrence) · 0616 第5波② ─────────────
# 团体 nodes are alias-fragmented (商务印书馆/商务书馆/商务书馆发行所 = one entity; 大生/大盛/大生事务所;
# 蟬隐庐/蝉隐庐). Two-layer merge: trad→simp char fold + curated ORG_CANON for the genuine
# multi-form entities (validated by identical surface-date fingerprints in probe). Rank by
# DISTINCT mention-days; each org → 主要人员 (top edge-linked persons) + 长编 (date/page/原文).
ORG_CANON = {
    '商务书馆': '商务印书馆', '商务书馆发行所': '商务印书馆', '商务印书馆发行所': '商务印书馆',
    '大生': '大生纱厂', '大盛': '大生纱厂', '大生事务所': '大生纱厂', '大生一、二、三厂': '大生纱厂',
    '大生纱厂二厂': '大生纱厂', '大生纱厂联合处': '大生纱厂', '大生沪账房': '大生纱厂',
    '宝经堂': '抱经堂', '抱经堂书店': '抱经堂',
    '徽宁会馆': '徽宁同乡会', '徽宁同乡会馆': '徽宁同乡会',
    '魏梅苏慈幼院': '慈幼院',
    '义振协会': '南陵义振协会', '南陵水灾义振协会': '南陵义振协会',
    '中国(汇兑银行)': '中国银行',
    '《安徽丛书》编纂处': '安徽丛书编印处', '安徽丛书编印处委员会': '安徽丛书编印处',
    '影印宋板藏经会': '影印宋版藏经会',
    '中国实业银行': '中国实业银行', '实业银行': '中国实业银行',
}


def canon_org(lbl):
    lbl = (lbl or '').strip().replace('蟬', '蝉').replace('舘', '馆')
    return ORG_CANON.get(lbl, lbl)


def org_kind(c):
    if any(k in c for k in ('书店', '书馆', '书局', '书社', '书庄', '书坊', '印书', '流通处',
                            '印社', '隐庐', '古香斋', '来青阁', '博古斋', '鸿宝斋', '藏经', '富晋')):
        return '书肆·出版'
    if any(k in c for k in ('纱厂', '纺织', '公司', '银行', '银号', '钱庄', '矿', '水泥',
                            '实业', '面粉', '电气', '电灯', '轮船', '盐垦')):
        return '实业·金融'
    if any(k in c for k in ('同乡会', '会馆')):
        return '同乡会馆'
    if any(k in c for k in ('义振', '赈', '慈幼', '济生', '仁济', '救', '善', '极贫', '医院', '医局')):
        return '慈善公益'
    if any(k in c for k in ('贞元会', '都益处', '聚丰园', '功德林', '小有天', '古益轩', '酒', '园', '楼')):
        return '雅集·饭庄'
    return '其他'


_org_dates = defaultdict(set)
_org_members = defaultdict(Counter)
_org_evid = defaultdict(list)
for _n in src['nodes']:
    if _n.get('entity_type') != '团体':
        continue
    _c = canon_org(_n.get('label'))
    for _sf in (_n.get('metadata') or {}).get('surface_forms') or []:
        if _sf.get('date'):
            _org_dates[_c].add(_sf['date'])
for _e in src['edges']:
    _s, _t = _e.get('source'), _e.get('target')
    for _oid, _other in ((_s, _t), (_t, _s)):
        if nodes_by_id.get(_oid, {}).get('entity_type') != '团体':
            continue
        _c = canon_org(nodes_by_id[_oid].get('label'))
        _d = _e.get('source_location')
        if _d:
            _org_dates[_c].add(_d)
        _on = nodes_by_id.get(redirect(_other) if nodes_by_id.get(_other, {}).get('entity_type') == '人' else _other, {})
        if _on.get('entity_type') == '人' and _on.get('label'):
            _org_members[_c][canonicalize_person(_on['label'])] += 1
        _ev = (_e.get('metadata') or {}).get('evidence_text')
        if _ev and _d:
            _org_evid[_c].append((_d, _ev.replace('\n', ' ').strip()))

_org_rank = sorted((c for c in _org_dates if c), key=lambda c: (-len(_org_dates[c]), c))
organizations = {'total_orgs': len(_org_dates), 'orgs': []}
for _c in _org_rank[:12]:
    _dates = sorted(_org_dates[_c])
    # fold 省称 into full name within this org (颂清⊂金颂清, 寄尘⊂吴寄尘, 子经⊂罗子经)
    _raw = _org_members[_c]
    _folded = {}
    for _nm in sorted((n for n in _raw if n and n != '徐乃昌'), key=len, reverse=True):
        _host = next((h for h in _folded if _nm in h), None)
        if _host:
            _folded[_host] += _raw[_nm]
        else:
            _folded[_nm] = _raw[_nm]
    _mem = [{'name': nm, 'n': cnt} for nm, cnt in
            sorted(_folded.items(), key=lambda kv: -kv[1])[:16]]
    _seen, _tl = set(), []
    for _d, _ev in sorted(_org_evid[_c]):
        if _d in _seen:
            continue
        _seen.add(_d)
        _tl.append({'date': _d, 'page': page_for(_d), 'snippet': _ev[:70]})
    organizations['orgs'].append({
        'org': _c, 'kind': org_kind(_c), 'days': len(_dates),
        'span': [_dates[0], _dates[-1]] if _dates else None,
        'members': _mem, 'member_total': len(_folded),
        'timeline': _tl[:80],
    })
(out_dir / 'organizations.json').write_text(
    json.dumps(organizations, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f"wrote Top {len(organizations['orgs'])} 团体 (of {organizations['total_orgs']} merged orgs); "
      f"#1 {organizations['orgs'][0]['org']} {organizations['orgs'][0]['days']}天")

_ORG_KIND_COLOR = {'书肆·出版': '#6a51a3', '实业·金融': '#2171b5', '同乡会馆': '#d94801',
                   '慈善公益': '#cb181d', '雅集·饭庄': '#1b7837', '其他': '#8c8c8c'}
_org_body = f"""
<div id="bars" class="card" style="padding:14px"></div>
<div style="margin-top:12px" class="card" id="browse"></div>
<script>
const ORG={json.dumps(organizations,ensure_ascii=False)};
const KC={json.dumps(_ORG_KIND_COLOR,ensure_ascii=False)};
const top=ORG.orgs.slice(0,10), mx=Math.max(...top.map(o=>o.days),1);
document.getElementById('bars').innerHTML='<div style="font-size:12px;color:#888;margin-bottom:10px">全库合并后共 '+ORG.total_orgs+' 个团体；下为出现天数最多的 Top10（已按本名/异写合并，如 商务印书馆/商务书馆/发行所）。点击查看主要人员与可回查长编。</div>'+
 top.map((o,i)=>{{const c=KC[o.kind]||'#888';return `<div data-i="${{i}}" class="obar" style="display:flex;align-items:center;gap:8px;margin:5px 0;cursor:pointer">
  <div style="width:24px;text-align:right;color:#bbada0;font-size:12px">${{i+1}}</div>
  <div style="width:128px;font-size:13px;font-weight:600">${{o.org}}</div>
  <div style="flex:1;background:#f0ece4;border-radius:3px"><div style="width:${{100*o.days/mx}}%;background:${{c}};height:18px;border-radius:3px"></div></div>
  <div style="width:108px;text-align:right;font-size:12px"><b>${{o.days}}</b> 天 · <span style="color:${{c}}">${{o.kind}}</span></div></div>`;}}).join('');
let cur=0;
function browse(){{
 const o=ORG.orgs[cur], c=KC[o.kind]||'#888';
 document.getElementById('browse').innerHTML=
  `<div style="font-size:15px;font-weight:700;margin-bottom:2px">${{cur+1}}. ${{o.org}} <span style="font-size:12px;font-weight:400;color:${{c}}">${{o.kind}}</span></div>`+
  `<div style="font-size:12px;color:#888;margin-bottom:8px">出现 <b>${{o.days}}</b> 天 · ${{o.span?o.span[0]+' → '+o.span[1]:''}} · 关联 ${{o.member_total}} 人</div>`+
  '<div style="margin-bottom:8px"><b style="font-size:12px;color:#666">主要人员：</b>'+
   o.members.map(m=>`<span style="display:inline-block;background:#f3efe9;border:1px solid #e2dccf;border-radius:10px;padding:1px 8px;font-size:12px;margin:2px 3px">${{m.name}} <span style="color:#bbada0">${{m.n}}</span></span>`).join('')+'</div>'+
  '<div style="font-size:12px;color:#666;margin:6px 0 4px"><b>事件长编</b>（可回查原书页码核对）：</div>'+
  '<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="color:#999;text-align:left"><th>日期</th><th>页</th><th>原文片段</th></tr>'+
   o.timeline.map(r=>`<tr><td style="padding:2px 6px 2px 0;white-space:nowrap">${{r.date}}</td><td style="color:#999;white-space:nowrap">${{r.page||''}}</td><td style="color:#5a5247">${{r.snippet}}</td></tr>`).join('')+'</table>';
}}
document.querySelectorAll('.obar').forEach(b=>b.onclick=()=>{{cur=+b.dataset.i;browse();}});
browse();
</script>"""
(specials_dir / 'organizations.html').write_text(_fig_page(
    '出现最多的团体 Top10',
    f'把全库 {organizations["total_orgs"]} 个团体（书肆·实业·同乡会·慈善·饭庄…）按在日记中出现的天数排名，'
    f'取前十。每个团体给出主要关联人员与可回查的事件长编（日期·原书页码·原文片段）。已按本名/异写合并，无重新抽取。',
    _org_body), encoding='utf-8')

# ── 南陵县志 · 史料长编 (0616 sheet2) ─────────────────────────────────────────
# 徐乃昌任《南陵县志》总纂。抽出"修志"全过程的史料长编，PRECISION 关键 = 必须 南陵-specific：
# gazetteer-PROCESS 词 (县志/修志/纂修/分纂/采访/访碑/拓碑/志书/局董…) ∧ 南陵 锚点 (南陵/宛陵/志局/
# 修志局/筹备修志局 — 本日记里"志局"专指南陵, 安徽通志用"通志局" — 或 principals 牧子襄/陈海汇/方朗夫/
# 盛彝斋/杨芷青/孙子彬, 含 OCR 异写 牧子襲/牧子壤)。OTHER-GAZ 守卫: 若仅含 安徽通志/泾县志… 而无硬南陵锚
# 点则剔除 (用户提示"有其他县志参杂进来")。访碑/拓碑 仅在南陵锚点下计入 (它们也用于金石收藏)。
# NOTE: 纂修/纂辑 dropped — they double as book-citation verbs ("蔡必达纂修本", "徐树穀纂辑")
# and produced the only residual false positives. 礼聘 entries still caught via 修志局/总纂/县志.
NL_PROC = ('县志', '修志', '总纂', '分纂', '修志局', '志稿', '局董', '分修',
           '采访', '访碑', '拓碑', '志书')
NL_ANCHOR = ('南陵', '宛陵', '南陵县', '南陵志', '修志局', '筹备修志局', '修志馆', '志局',
             '牧子襄', '牧子襲', '牧子壤', '陈海汇', '方朗夫', '盛彝斋', '杨芷青', '孙子彬')
NL_HARD = ('南陵', '宛陵', '南陵县', '南陵志', '牧子襄', '牧子襲', '牧子壤',
           '陈海汇', '方朗夫', '盛彝斋', '杨芷青', '孙子彬')
NL_OTHER = ('安徽通志', '通志局', '皖志局', '江南通志', '江苏通志', '浙江通志', '一统志',
            '泾县志', '宣城县志', '太平府志')
NL_PRINCIPALS = {'牧子襄': ('牧子襄', '牧子襲', '牧子壤'), '陈海汇': ('陈海汇',),
                 '方朗夫': ('方朗夫',), '盛彝斋': ('盛彝斋', '彝斋'), '杨芷青': ('杨芷青',),
                 '孙子彬': ('孙子彬',), '吴舜臣': ('吴舜臣', '舜臣', '舜老')}


def _nl_phase(b):
    if any(k in b for k in ('敦请', '婉辞', '束脩', '延纂', '辞纂', '请主修', '主修', '聘请', '总纂')):
        return '礼聘·受任'
    if any(k in b for k in ('排印', '校样', '付印', '石印', '印工', '刊样', '刻样', '排工', '付刊', '刊成')):
        return '刊印·校样'
    if any(k in b for k in ('运芜', '部数', '结欠', '带回', '函索', '清单', '县志部', '地图套', '归还我处')):
        return '分发·结账'
    if any(k in b for k in ('分纂', '采访', '访碑', '拓碑', '编辑', '分修', '志稿', '舆图', '艺文',
                            '经籍', '金石志', '碑碣', '人物志', '舆地', '分门', '商订', '编《', '原本县志')):
        return '纂修·采访'
    return '志事往来'


def _has(b, kws):
    return any(k in b for k in kws)


nl_entries = []
_nl_principal_days = Counter()
_nl_phase_days = Counter()
for _d in sorted(_BODY):
    _b = _BODY[_d]
    if not _has(_b, NL_PROC):
        continue
    if not _has(_b, NL_ANCHOR):
        continue
    if _has(_b, NL_OTHER) and not _has(_b, NL_HARD):     # other-gazetteer leak → drop
        continue
    _kw = next((k for k in NL_PROC if k in _b), '')
    _pos = _b.find(_kw)
    _snip = _b[max(0, _pos - 14):_pos + 40].replace('\n', ' ').strip()
    _princ = [nm for nm, al in NL_PRINCIPALS.items() if any(a in _b for a in al)]
    for nm in _princ:
        _nl_principal_days[nm] += 1
    _ph = _nl_phase(_b)
    _nl_phase_days[_ph] += 1
    nl_entries.append({'date': _d, 'page': page_for(_d), 'kw': _kw, 'phase': _ph,
                       'principals': _princ, 'snippet': _snip})

_PHASE_ORDER = ['礼聘·受任', '纂修·采访', '刊印·校样', '分发·结账', '志事往来']
nanling = {
    'total_days': len(nl_entries),
    'span': [nl_entries[0]['date'], nl_entries[-1]['date']] if nl_entries else None,
    'by_year': dict(sorted(Counter(e['date'][:4] for e in nl_entries).items())),
    'by_phase': [{'phase': p, 'days': _nl_phase_days.get(p, 0)} for p in _PHASE_ORDER],
    'principals': [{'name': nm, 'days': c} for nm, c in _nl_principal_days.most_common()],
    'entries': nl_entries,
}
(out_dir / 'nanling_gazetteer.json').write_text(
    json.dumps(nanling, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f"wrote 南陵县志 史料长编: {nanling['total_days']} 天 "
      f"({nanling['span'][0] if nanling['span'] else '-'}→{nanling['span'][1] if nanling['span'] else '-'}), "
      f"principals {[p['name'] for p in nanling['principals'][:4]]}")

_NL_PHASE_COLOR = {'礼聘·受任': '#9b2926', '纂修·采访': '#1b7837', '刊印·校样': '#2171b5',
                   '分发·结账': '#a35c1a', '志事往来': '#8c8c8c'}
_nl_body = f"""
<div class="card" style="padding:14px" id="hdr"></div>
<div style="margin-top:12px" class="card" id="tl" style="padding:10px"></div>
<script>
const NL={json.dumps(nanling,ensure_ascii=False)};
const PC={json.dumps(_NL_PHASE_COLOR,ensure_ascii=False)};
const mxp=Math.max(...NL.by_phase.map(p=>p.days),1);
let h=`<div style="font-size:12px;color:#888;margin-bottom:8px">徐乃昌任《南陵县志》总纂。共 <b style="color:#9b2926">${{NL.total_days}}</b> 天志事，${{NL.span?NL.span[0]+' → '+NL.span[1]:''}}。已按"修志词∧南陵锚点"精筛，剔除安徽通志/他县志杂入。</div>`;
h+='<div style="display:flex;flex-wrap:wrap;gap:14px">';
h+='<div style="flex:1;min-width:240px"><b style="font-size:12px;color:#666">分阶段</b>'+
 NL.by_phase.map(p=>`<div style="display:flex;align-items:center;gap:6px;margin:3px 0"><div style="width:64px;font-size:12px">${{p.phase}}</div><div style="flex:1;background:#f0ece4;border-radius:3px"><div style="width:${{100*p.days/mxp}}%;height:14px;background:${{PC[p.phase]}};border-radius:3px"></div></div><div style="width:40px;text-align:right;font-size:12px">${{p.days}}天</div></div>`).join('')+'</div>';
h+='<div style="flex:1;min-width:240px"><b style="font-size:12px;color:#666">主要纂修人员（命中天数）</b><div style="margin-top:4px">'+
 NL.principals.map(p=>`<span style="display:inline-block;background:#f3efe9;border:1px solid #e2dccf;border-radius:10px;padding:1px 9px;font-size:12px;margin:2px 3px">${{p.name}} <span style="color:#bbada0">${{p.days}}</span></span>`).join('')+'</div></div>';
h+='</div>';
document.getElementById('hdr').innerHTML=h;
// chronological 长编
let cur='全部';
function tl(){{
 const es=NL.entries.filter(e=>cur==='全部'||e.phase===cur);
 const phases=['全部'].concat(NL.by_phase.filter(p=>p.days).map(p=>p.phase));
 document.getElementById('tl').innerHTML=
  '<div style="margin-bottom:8px">'+phases.map(p=>`<button data-p="${{p}}" style="margin:0 6px 4px 0;padding:3px 10px;border:1px solid #ddd;border-radius:3px;cursor:pointer;background:${{p===cur?(PC[p]||'#666'):'#fff'}};color:${{p===cur?'#fff':'#333'}}">${{p}}</button>`).join('')+'</div>'+
  `<div style="font-size:12px;color:#888;margin-bottom:6px">${{es.length}} 条 · 点击可对原书页码回查中华经典古籍库</div>`+
  '<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="color:#999;text-align:left"><th>日期</th><th>页</th><th>阶段</th><th>命中</th><th>人物</th><th>原文片段</th></tr>'+
  es.map(e=>`<tr style="border-top:1px solid #f3efe9"><td style="padding:3px 6px 3px 0;white-space:nowrap">${{e.date}}</td><td style="color:#999;white-space:nowrap">${{e.page||''}}</td><td style="color:${{PC[e.phase]||'#666'}};white-space:nowrap">${{e.phase}}</td><td style="color:#9b2926;white-space:nowrap">${{e.kw}}</td><td style="color:#7a6a55;white-space:nowrap">${{(e.principals||[]).join('、')}}</td><td style="color:#5a5247">${{e.snippet}}</td></tr>`).join('')+'</table>';
 document.querySelectorAll('#tl button').forEach(b=>b.onclick=()=>{{cur=b.dataset.p;tl();}});
}}
tl();
</script>"""
(specials_dir / 'nanling-gazetteer.html').write_text(_fig_page(
    '南陵县志 · 史料长编',
    f'徐乃昌任《南陵县志》总纂（1920 礼聘 → 1924 刊成 → 1930 前后分发结账）。本页把修志全过程的 '
    f'{nanling["total_days"]} 条史料按时间编为长编：每条给出原书页码、所处阶段、命中词、在场纂修人员与原文片段。'
    f'已用"修志词 ∧ 南陵锚点"精筛，剔除安徽通志/他县县志的杂入（用户校样反馈）。',
    _nl_body), encoding='utf-8')

# Figure 1 — concentric rings (SVG, computed client-side)
RING_COLORS = ['#9b2926', '#c0392b', '#d98880', '#e8b9b3', '#cfcabf']
_f1_body = f"""
<div class="legend" id="lg"></div>
<div class="card"><svg id="svg" viewBox="0 0 920 920" style="width:100%;height:auto"></svg></div>
<script>
const RINGS={json.dumps(rings,ensure_ascii=False)};
const RLAB={json.dumps(RING_LABELS,ensure_ascii=False)};
const COL={json.dumps(RING_COLORS)};
const RAD=[0,150,260,360,440];
const cx=460,cy=460;
const svg=document.getElementById('svg');
function el(t,a){{const e=document.createElementNS('http://www.w3.org/2000/svg',t);for(const k in a)e.setAttribute(k,a[k]);return e;}}
// ring guide circles
[1,2,3,4].forEach(r=>{{svg.appendChild(el('circle',{{cx,cy,r:RAD[r],fill:'none',stroke:'#e7e0d6','stroke-dasharray':'3 4'}}));
 svg.appendChild(el('text',{{x:cx,y:cy-RAD[r]+14,fill:'#bbada0','font-size':11,'text-anchor':'middle'}})).textContent=RLAB[r];}});
// center 徐乃昌
svg.appendChild(el('circle',{{cx,cy,r:18,fill:COL[0]}}));
const ct=el('text',{{x:cx,y:cy+34,fill:'#2b2622','font-size':13,'font-weight':700,'text-anchor':'middle'}});ct.textContent='徐乃昌';svg.appendChild(ct);
// group by ring, place evenly
const byR={{}};RINGS.forEach(p=>{{(byR[p.ring]=byR[p.ring]||[]).push(p);}});
[1,2,3,4].forEach(r=>{{const arr=byR[r]||[];const n=arr.length;arr.forEach((p,i)=>{{
 const ang=(i/Math.max(n,1))*2*Math.PI - Math.PI/2;
 const x=cx+RAD[r]*Math.cos(ang), y=cy+RAD[r]*Math.sin(ang);
 const f=p.xu_freq||0;
 const rad=Math.max(3,Math.min(13,3+Math.sqrt(f)));
 const c=el('circle',{{cx:x,cy:y,r:rad,fill:COL[r],opacity:0.85}});
 c.appendChild(el('title',{{}}));c.lastChild.textContent=`${{p.label}} · 与徐互动${{f}}`+(p.kin_type?` · ${{p.kin_type}}`:'')+(p.jiguan?` · ${{p.jiguan}}`:'');
 svg.appendChild(c);
 if(f>=(r<=2?4:10)){{const tx=el('text',{{x:x+(x>=cx?rad+2:-rad-2),y:y+3,'font-size':10,fill:'#5a5247','text-anchor':x>=cx?'start':'end'}});tx.textContent=p.label;svg.appendChild(tx);}}
}});}});
const lg=document.getElementById('lg');
[0,1,2,3,4].forEach(r=>{{const s=document.createElement('span');s.innerHTML=`<span class="dot" style="background:${{COL[r]}}"></span>${{RLAB[r]}}`;lg.appendChild(s);}});
</script>"""
(specials_dir / 'relationship-rings.html').write_text(_fig_page(
    '人物关系同心圆',
    f'以徐乃昌为核心，按关系亲疏分层：亲属 → 南陵同乡 → 安徽同乡 → 其他。'
    f'全库分层人数：亲属 {ring_counts.get("亲属",0)}·南陵同乡 {ring_counts.get("南陵同乡",0)}'
    f'·安徽同乡 {ring_counts.get("安徽同乡",0)}·其他 {ring_counts.get("其他",0)}。'
    f'<b>点大小 = 其与徐乃昌的互动频次</b>（直接往来＋同席）；外两层只画与徐互动最多者'
    f'（安徽 {RING_CAP[3]}、其他 {RING_CAP[4]}）。皖籍打标已补全（同乡会同席＋籍贯陈述＋亲属推断），'
    f'故安徽圈较前充实；“其他”圈中仍多是徐在沪的江浙闽藏书友（陈乃乾·李拔可·张元济·刘翰怡等），'
    f'确非皖人——这正说明徐的核心交游是<b>跨地域的书林</b>，而非纯乡谊。'
    f'“一图概括所有 {per_unique} 人”见 → 人物同现总图。',
    _f1_body), encoding='utf-8')

# Figure 2 — 事业 clusters (Cytoscape)
_f2_body = f"""
<div class="legend" id="lg"></div>
<div class="card"><div id="cy" style="height:680px"></div></div>
<script src="https://unpkg.com/cytoscape@3/dist/cytoscape.min.js"></script>
<script>
const DATA={json.dumps(clusters,ensure_ascii=False)};
const TC={json.dumps(TYPE_COLOR,ensure_ascii=False)};
const els=[];const seen=new Set();
DATA.projects.forEach(p=>{{
 els.push({{data:{{id:'P:'+p.project,label:p.project,kind:'proj',color:TC[p.type]||'#777'}}}});
 p.persons.forEach(a=>{{
   const pid='A:'+a;
   if(!seen.has(pid)){{seen.add(pid);const ov=DATA.overlap[a];
     els.push({{data:{{id:pid,label:a,kind:ov?'overlap':'per',deg:ov?ov.length:1}}}});}}
   els.push({{data:{{source:'P:'+p.project,target:pid}}}});
 }});
}});
const cy=cytoscape({{container:document.getElementById('cy'),elements:els,
 style:[
  {{selector:'node[kind="proj"]',style:{{'shape':'round-rectangle','background-color':'data(color)','label':'data(label)','color':'#fff','font-size':11,'text-valign':'center','text-wrap':'wrap','text-max-width':90,'width':100,'height':34,'padding':'4px'}}}},
  {{selector:'node[kind="per"]',style:{{'background-color':'#b9b2a6','label':'data(label)','font-size':9,'width':14,'height':14,'color':'#5a5247','text-valign':'bottom'}}}},
  {{selector:'node[kind="overlap"]',style:{{'background-color':'#9b2926','label':'data(label)','font-size':11,'font-weight':'bold','width':'mapData(deg,2,5,20,40)','height':'mapData(deg,2,5,20,40)','color':'#9b2926','text-valign':'bottom','border-width':2,'border-color':'#fff'}}}},
  {{selector:'edge',style:{{'width':1,'line-color':'#d8d0c4','curve-style':'bezier'}}}}
 ],
 layout:{{name:'cose',animate:false,nodeRepulsion:9000,idealEdgeLength:70,padding:30}}}});
const lg=document.getElementById('lg');
Object.entries(TC).forEach(([k,v])=>{{const s=document.createElement('span');s.innerHTML=`<span class="dot" style="background:${{v}}"></span>${{k}}`;lg.appendChild(s);}});
const o=document.createElement('span');o.innerHTML='<span class="dot" style="background:#9b2926"></span>跨事业重叠人物 (≥2 项目)';lg.appendChild(o);
</script>"""
(specials_dir / 'shiye-clusters.html').write_text(_fig_page(
    '事业聚合与重叠',
    f'按事业聚合人物：{len(clu_projects)} 个项目、{len(overlap)} 位跨事业重叠人物 (红色加大)。'
    f'重叠揭示同一群人横跨多项事业 (如修志 ↔ 赈灾)。',
    _f2_body), encoding='utf-8')

# Figure 3 — geo heatmap (Leaflet + heat)
_f3_head = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1/dist/leaflet.css">'
            '<script src="https://unpkg.com/leaflet@1/dist/leaflet.js"></script>'
            '<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>')
_f3_body = f"""
<div class="legend"><label><input type="radio" name="who" id="rball" checked> 徐乃昌+家人(并集)</label>
 <label><input type="radio" name="who" id="rbxu"> 仅徐乃昌</label>
 <label><input type="radio" name="who" id="rbfam"> 仅家人</label>
 <span style="color:#888">圈大小/热度 = 该地<b>不同天数</b>（非提及次数）</span></div>
<div style="display:flex;gap:12px;flex-wrap:wrap">
 <div class="card" style="flex:2;min-width:420px"><div id="map" style="height:560px;border-radius:6px"></div></div>
 <div class="card" style="flex:1;min-width:230px">
   <div style="font-size:12px;font-weight:700;margin-bottom:6px">高频地点（按天数）</div>
   <table id="tbl" style="width:100%;border-collapse:collapse;font-size:12px"></table></div>
</div>
<script>
const TRAJ={json.dumps(trajectory,ensure_ascii=False)};
const map=L.map('map',{{preferCanvas:true}}).setView([31.5,119],6);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
 {{attribution:'&copy; OpenStreetMap &copy; CARTO',subdomains:'abcd',maxZoom:12}}).addTo(map);
function val(t){{const m=document.getElementById('rbxu').checked?'days_xu':
  document.getElementById('rbfam').checked?'days_family':'days';return t[m]||0;}}
let hlayer=null, dots=[];
function draw(){{
 const rows=TRAJ.map(t=>({{...t,v:val(t)}})).filter(t=>t.v>0).sort((a,b)=>b.v-a.v);
 const mx=Math.max(...rows.map(r=>r.v),1);
 if(hlayer)map.removeLayer(hlayer);
 hlayer=L.heatLayer(rows.map(r=>[r.lat,r.lng,r.v]),{{radius:24,blur:18,maxZoom:10,max:mx,
   gradient:{{0.15:'#3a78b5',0.4:'#8bbf4f',0.6:'#f0c419',0.8:'#e8731a',1.0:'#9b2926'}}}}).addTo(map);
 dots.forEach(d=>map.removeLayer(d));dots=[];
 rows.slice(0,16).forEach(r=>{{
   const rad=4+14*Math.sqrt(r.v/mx);
   const c=L.circleMarker([r.lat,r.lng],{{radius:rad,color:'#9b2926',weight:1,fillColor:'#9b2926',fillOpacity:0.25}})
     .addTo(map).bindTooltip(`${{r.place}} · ${{r.v}}天`,{{direction:'top'}});
   dots.push(c);
 }});
 const tb=document.getElementById('tbl');tb.innerHTML='<tr style="color:#999"><th style="text-align:left">地点</th><th style="text-align:right">天数</th></tr>'+
   rows.slice(0,18).map(r=>`<tr><td style="padding:2px 0;border-bottom:1px solid #f0ece4">${{r.place}}</td><td style="text-align:right;color:#9b2926">${{r.v}}</td></tr>`).join('');
}}
['rball','rbxu','rbfam'].forEach(id=>document.getElementById(id).onchange=draw);
draw();
const b=L.latLngBounds(TRAJ.map(t=>[t.lat,t.lng]));if(TRAJ.length)map.fitBounds(b.pad(0.1));
</script>
<style>.pl{{background:rgba(255,255,255,.85);border:none;box-shadow:none;font-size:11px;color:#5a5247}}</style>"""
_nl_days = next((t['days'] for t in trajectory if t['place'] == '南陵'), 0)
_wh_days = next((t['days'] for t in trajectory if t['place'] == '芜湖'), 0)
(specials_dir / 'trajectory-heatmap.html').write_text(_fig_page(
    '作者及家人行迹热力图',
    f'徐乃昌本人及 {len(family)} 位家人的行迹，按<b>不同天数</b>计热度（非提及次数）。'
    f'家人行迹纳入：徐未返乡时妻/子女代行清明祭祖、年节等。南陵 {_nl_days} 天、芜湖 {_wh_days} 天均已计入。静态图，可截图入论文。',
    _f3_body, head_extra=_f3_head), encoding='utf-8')

print(f'figures: overview {overview_graph["shown"]}/{overview_graph["unique_total"]} ppl | '
      f'rings {sum(ring_counts.values())} {ring_counts} | '
      f'clusters {len(clu_projects)} proj / {len(overlap)} overlap | '
      f'trajectory {len(trajectory)} places (南陵{_nl_days}天 芜湖{_wh_days}天) family={len(family)}')
print(f'事件性质(按天·多标签): ' + ' '.join(f'{c}={event_nature["counts"][c]}' for c in NATURE_ORDER)
      + f' / 共{event_nature["total_days"]}天')

# Index
specials_idx = [
    f'<nav><a href="../index.html">← 返回总览</a></nav>',
    '<h1>专题策展</h1>',
    '<div class="meta">数据驱动的主题页：从分散日记条目里按议题聚合。点击主题进入。</div>',
    '<ul>',
    '<li><a href="people-overview.html"><strong>人物同现总图</strong></a> — 一图概括全部人物 (论文图4 风格) + unique 人数</li>',
    '<li><a href="relationship-rings.html"><strong>人物关系同心圆</strong></a> — 亲疏分层 (亲属/南陵/安徽/其他)，点大小=与徐互动频次</li>',
    '<li><a href="organizations.html"><strong>出现最多的团体 Top10</strong></a> — 书肆/实业/同乡会/慈善，主要人员+事件长编</li>',
    '<li><a href="nanling-gazetteer.html"><strong>南陵县志·史料长编</strong></a> — 徐乃昌总纂修志全程，精筛剔除他县志</li>',
    '<li><a href="shiye-clusters.html"><strong>事业聚合与重叠</strong></a> — 人物×事业 (含金石/诗词圈)，跨事业重叠</li>',
    '<li><a href="event-nature.html"><strong>日记事件性质分类</strong></a> — 金石/诗词/遗民/乡邦/其它 按天计数</li>',
    '<li><a href="event-types.html"><strong>生活事件类型 Top10</strong></a> — 全 6134 天 11 类活动排名 (确定性，无 LLM)</li>',
    '<li><a href="wu-shunchen.html"><strong>吴舜臣·收租代理活动谱</strong></a> — 逐月活动 + 与 0615 人工检索逐年对照</li>',
    '<li><a href="trajectory-heatmap.html"><strong>作者及家人行迹热力图</strong></a> — 按天数计 · 静态地理热力 (论文用)</li>',
    '<li><a href="recall-audit.html"><strong>召回审计</strong></a> — 原文全文检索 vs 图谱覆盖率 (无重新抽取)</li>',
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
