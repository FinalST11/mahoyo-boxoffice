#!/usr/bin/env python3
"""每小时由 GitHub Actions 运行：从 mimorin2014.com 抓《魔法使いの夜》的全天合算数字，追加到 data/sample.csv。

规则（与每日 AI 任务一致）：
- 只用标题恰好为「デイリー合算ランキング：YYYYMMDD(曜)」的全天最终帖（不是中間集計，也不是「独立系を含む」）。
- 日期 D 的全天帖发在 D+1 的日期页上；被挤出日期页时，按 blog-entry 编号往前找。
- 同名多行：販売数/座席数/回数相加，館数取最大，順位取最小，note 写明合并了几行。
- 第 8 天起用原帖的「先週比」核对：不符时写入 note。
- 帖子还没发出来就停下，下次再试；不会跳过日期。
只用 Python 标准库，不需要任何密钥。
"""
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, 'data', 'sample.csv')
STATUS = os.path.join(ROOT, 'data', 'status.json')
BASE = 'https://mimorin2014.com'
FILM, FILM_NAME, TITLE = 'MAHO', '魔法使いの夜', '魔法使いの夜'
DAY0 = dt.date(2026, 11, 19)  # 2026-11-20 是第 1 天
JST = dt.timezone(dt.timedelta(hours=9))
WD = '一二三四五六日'
WD_JA = '月火水木金土日'
UA = 'Mozilla/5.0 (compatible; mahoyo-boxoffice tracker; +https://finalst11.github.io/mahoyo-boxoffice/)'
ROW = re.compile(r'^\s*([\*\d]{1,3})　([\*\d]+)　([\*\d]+)　([\*\d]+)　([\*\d]+)　([\*\d\.%]+)　(.+?)\s*$')
ENTRY = re.compile(r'id="e(\d+)">\s*<h2 class="entry_header"><a href="[^"]*blog-entry-\d+\.html"[^>]*>\s*(.*?)\s*</a>', re.S)

_last = [0.0]


def get(url):
    wait = 2.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                _last[0] = time.time()
                return r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code == 404:
                return None
            if attempt == 0:
                time.sleep(20)
                continue
            raise
        except Exception:
            _last[0] = time.time()
            if attempt == 0:
                time.sleep(20)
                continue
            raise


def num(s):
    s = s.replace('*', '')
    return int(s) if s.isdigit() else None


def target_title(d):
    return f'デイリー合算ランキング：{d:%Y%m%d}({WD_JA[d.weekday()]})'


def find_entry(d):
    """返回日期 D 全天最终帖的 entry 编号；找不到返回 None。"""
    want = target_title(d)
    page = get(f'{BASE}/blog-date-{d + dt.timedelta(days=1):%Y%m%d}.html')
    if not page:
        return None
    entries = [(int(i), html.unescape(re.sub(r'\s+', '', t))) for i, t in ENTRY.findall(page)]
    for i, t in entries:
        if t == want:
            return i
    if not entries:
        return None
    # 被挤出日期页：从页面上最小的编号往前找
    n = min(i for i, _ in entries)
    for k in range(1, 11):
        p = get(f'{BASE}/blog-entry-{n - k}.html')
        if not p:
            continue
        m = re.search(r'<h2 class="entry_header">.*?>\s*(.*?)\s*</a>', p, re.S)
        t = html.unescape(re.sub(r'\s+', '', m.group(1))) if m else ''
        if t == want:
            return n - k
        # 编号已经退到更早一天的帖子，就不用再找了
        dm = re.search(r'：(\d{8})\(', t)
        if dm and dm.group(1) < f'{d:%Y%m%d}':
            break
    return None


def parse_entry(eid):
    page = get(f'{BASE}/blog-entry-{eid}.html')
    if not page:
        return None
    start = page.find(f'id="e{eid}"')
    body = page[start:] if start >= 0 else page
    nxt = re.search(r'id="e\d+"|class="entry_footer"|id="cm"', body[20:])
    if nxt:
        body = body[:20 + nxt.start()]
    lines = [html.unescape(re.sub(r'<[^>]+>', '', x)) for x in re.split(r'<br\s*/?>', body)]
    rows = [m.groups() for m in (ROW.match(l) for l in lines) if m]
    return rows


def main():
    with open(SAMPLE, encoding='utf-8', newline='') as f:
        text = f.read()
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames
    rows = list(reader)
    maho = [r for r in rows if r['film'] == FILM]
    last = max(dt.date.fromisoformat(r['date']) for r in maho)
    by_day = {int(r['day']): r for r in maho}
    today = dt.datetime.now(JST).date()
    yesterday = today - dt.timedelta(days=1)

    added = []
    d = last + dt.timedelta(days=1)
    while d <= yesterday:
        eid = find_entry(d)
        if eid is None:
            print(f'{d}: 全天帖还没找到，下次再试')
            break
        all_rows = parse_entry(eid)
        if not all_rows:
            print(f'{d}: entry {eid} 解析不到表格，下次再试')
            break
        hit = [r for r in all_rows if r[6].strip() == TITLE or r[6].strip().startswith(TITLE + '（') or r[6].strip().startswith(TITLE + '(')]
        day = (d - DAY0).days
        row = {k: '' for k in fields}
        row.update(film=FILM, film_name=FILM_NAME, day=str(day), date=d.isoformat(), weekday=WD[d.weekday()], measure='全日')
        notes = []
        if hit:
            row['rank'] = str(min(num(h[0]) for h in hit))
            row['sales'] = str(sum(num(h[1]) or 0 for h in hit))
            row['seats'] = str(sum(num(h[2]) or 0 for h in hit))
            row['shows'] = str(sum(num(h[3]) or 0 for h in hit))
            row['theaters'] = str(max(num(h[4]) or 0 for h in hit))
            if len(hit) > 1:
                notes.append(f'合并{len(hit)}行')
            wow = hit[0][5].replace('*', '')
            prev = by_day.get(day - 7)
            if day >= 8 and len(hit) == 1 and wow.endswith('%') and prev and prev.get('sales'):
                calc = int(row['sales']) / int(prev['sales']) * 100
                if abs(calc - float(wow[:-1])) > 0.1:
                    notes.append(f'先週比不符：原帖{wow}')
        else:
            notes.append('全天榜未进前25')
        notes.append('自动抓取')
        row['note'] = '；'.join(notes)
        rows.append(row)
        by_day[day] = row
        added.append(row)
        print(f'{d}: 第{day}天 entry {eid} → 排名 {row["rank"]} 售票 {row["sales"]} {row["note"]}')
        d += dt.timedelta(days=1)

    if not added:
        print('没有新数据')
        return 0

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    with open(SAMPLE, 'w', encoding='utf-8', newline='') as f:
        f.write(out.getvalue())
    now = dt.datetime.now(JST).replace(microsecond=0)
    status = {}
    if os.path.exists(STATUS):
        with open(STATUS, encoding='utf-8') as f:
            status = json.load(f)
    status.update(updated_at=now.isoformat(), updated_by='GitHub Actions（每小时自动抓取）', latest_date=added[-1]['date'])
    with open(STATUS, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write('\n')
    gh = os.environ.get('GITHUB_OUTPUT')
    if gh:
        with open(gh, 'a') as f:
            f.write(f'added={added[0]["date"]}~{added[-1]["date"]}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
