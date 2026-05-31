"""
Recall audit (no re-extraction). Reproduces the user's 检查方式 = full-text search
on 中华经典古籍库 by grepping the 6142 source chunks (data/poc_200/*.md), then
compares against what the graph / views actually surface.

For each audited concept:
  source_dates   = chunk dates whose body contains the keyword(s)   [ground truth]
  graph_dates    = chunk dates the graph/views cover for that concept
  coverage_pct   = |graph_dates ∩ source_dates| / |source_dates|
  missed         = source_dates − graph_dates  (sample listed)

Modes:
  node   concept covered if any node label / surface / edge evidence on that date
         contains the keyword (= did extraction surface the concept at all)
  price  稻谷单价: covered if a txn on that date has unit_price_yuan filled
  agent  经办人: covered if a txn on that date is attributed to the given agent

Run:  python recall_audit.py        # prints table + writes data/recall_audit.json
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
MD_DIR = ROOT / 'data' / 'poc_200'
SEMANTIC = ROOT / 'data' / 'poc_200' / '.graphify_semantic.json'
OUT = Path(__file__).parent / 'data' / 'recall_audit.json'

DATE_RX = re.compile(r'(\d{4}-\d{2}-\d{2})')

AUDITS = [
    {'key': '每石·稻谷单价', 'kw': ['每石'], 'mode': 'price'},
    {'key': '吴舜臣·实体召回', 'kw': ['舜臣'], 'mode': 'node'},
    {'key': '吴舜臣·经办归属', 'kw': ['舜臣'], 'mode': 'agent', 'agent': '吴舜臣'},
    # node = extraction surfaced the concept as an entity; shiye = the 事业 project
    # covers that source day (node ∪ Tier-2 text) — the S3 acceptance metric.
    {'key': '垦务·万顷湖/万春湖 (node)', 'kw': ['万顷湖', '万春湖'], 'mode': 'node'},
    {'key': '垦务·万顷湖/万春湖 (事业)', 'kw': ['万顷湖', '万春湖'], 'mode': 'shiye', 'proj': '垦务·万顷湖/万春湖'},
    {'key': '编《安徽通志》 (node)', 'kw': ['安徽通志'], 'mode': 'node'},
    {'key': '编《安徽通志》 (事业)', 'kw': ['安徽通志'], 'mode': 'shiye', 'proj': '编《安徽通志》'},
    {'key': '同乡会·会馆 (node)', 'kw': ['同乡会', '徽宁会馆', '旅沪'], 'mode': 'node'},
    {'key': '同乡会·会馆 (事业)', 'kw': ['同乡会', '徽宁会馆', '旅沪'], 'mode': 'shiye', 'proj': '同乡会·会馆'},
    {'key': '赈务 (node)', 'kw': ['赈', '义振', '放赈', '急赈'], 'mode': 'node'},
    {'key': '赈务 (事业)', 'kw': ['赈', '义振', '放赈', '急赈'], 'mode': 'shiye', 'proj': '赈务'},
    {'key': '家族·三太太/大太太 (node)', 'kw': ['三太太', '大太太'], 'mode': 'node'},
    {'key': '家族事务 (事业)', 'kw': ['三太太', '大太太', '族叔', '族长', '祠堂', '祭祖', '扫墓'],
     'mode': 'shiye', 'proj': '家族事务'},
]


def stem_date(p):
    m = DATE_RX.search(p.stem)
    return m.group(1) if m else p.stem


# ── source ground truth: date → body ─────────────────────────────────────────
src_body = {}
for p in sorted(MD_DIR.glob('*.md')):
    try:
        src_body[stem_date(p)] = p.read_text(encoding='utf-8')
    except Exception:
        pass


def source_dates_for(kws):
    return {d for d, body in src_body.items() if any(k in body for k in kws)}


# ── graph text index by date (node labels + surfaces + edge evidence) ─────────
graph = json.loads(SEMANTIC.read_text(encoding='utf-8'))
node_text_by_date = defaultdict(list)
for n in graph['nodes']:
    d = n.get('captured_at')
    if not d:
        continue
    node_text_by_date[d].append(n.get('label') or '')
    for sf in ((n.get('metadata') or {}).get('surface_forms') or []):
        node_text_by_date[d].append(sf.get('surface') or '')
for e in graph['edges']:
    d = e.get('source_location')
    ev = (e.get('metadata') or {}).get('evidence_text')
    if d and ev:
        node_text_by_date[d].append(ev)
graph_text_by_date = {d: ''.join(parts) for d, parts in node_text_by_date.items()}


def node_dates_for(kws):
    return {d for d, blob in graph_text_by_date.items() if any(k in blob for k in kws)}


# ── view-derived coverage (transactions.json) ────────────────────────────────
txns = json.loads((Path(__file__).parent / 'data' / 'transactions.json').read_text(encoding='utf-8'))
price_dates = {t['date'] for t in txns if t.get('unit_price_yuan') is not None and t.get('date')}
agent_dates = defaultdict(set)
for t in txns:
    if t.get('agent') and t.get('date'):
        agent_dates[t['agent']].add(t['date'])

# ── 事业 project day-coverage (shiye.json member_dates) ───────────────────────
_shiye_path = Path(__file__).parent / 'data' / 'shiye.json'
shiye_dates = {}
if _shiye_path.exists():
    for r in json.loads(_shiye_path.read_text(encoding='utf-8')):
        shiye_dates[r['project']] = set(r.get('member_dates') or [])


def run():
    rows = []
    for a in AUDITS:
        src_dates = source_dates_for(a['kw'])
        if a['mode'] == 'price':
            cov = price_dates & src_dates
        elif a['mode'] == 'agent':
            cov = agent_dates.get(a['agent'], set()) & src_dates
        elif a['mode'] == 'shiye':
            cov = shiye_dates.get(a['proj'], set()) & src_dates
        else:
            cov = node_dates_for(a['kw']) & src_dates
        missed = sorted(src_dates - cov)
        pct = round(100 * len(cov) / len(src_dates), 1) if src_dates else None
        rows.append({
            'concept': a['key'],
            'mode': a['mode'],
            'keywords': a['kw'],
            'source_chunks': len(src_dates),
            'graph_covered': len(cov),
            'coverage_pct': pct,
            'missed_count': len(missed),
            'missed_sample': missed[:25],
        })
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{"concept":24} {"src":>5} {"cov":>5} {"pct":>6}  missed')
    print('-' * 60)
    for r in rows:
        print(f'{r["concept"]:24} {r["source_chunks"]:5d} {r["graph_covered"]:5d} '
              f'{str(r["coverage_pct"]):>6}  {r["missed_count"]}')
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    run()
