#!/usr/bin/env python3
"""每小时由 GitHub Actions 运行：从新闻 RSS 里找《魔法使いの夜》新的官方累计动员/票房，追加到 data/milestones.csv。

官方数字只在官方 X 上公布，媒体会全文转载或引用。这里读几家媒体的 RSS，
标题提到「魔法使いの夜」和票房/动员的文章，打开正文，找下面这些写法：
  ・「11月20日(金)～22日(日)の3日間で観客動員256,305人(興行収入451,494,100円)」
  ・「公開4日間で観客動員30万1630人、興行収入5億2613万2800円」
  ・「12月6日時点で観客動員xxx人、興行収入xxx円」
只接受精确到个位的数字（「30万人」「5億円」这种约数不要），并做合理性检查：
比现有最新节点更晚、更大，平均票价在 1,200～2,600 日元之间。
新增的行在 source_note 里标「自动抓取（待核对）」，每天的 AI 任务会再核对一次。
只用 Python 标准库。
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
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MILESTONES = os.path.join(ROOT, 'data', 'milestones.csv')
SEEN = os.path.join(ROOT, 'data', 'official_seen.json')
DAY0 = dt.date(2026, 11, 19)  # 2026-11-20 是第 1 天
RELEASE = dt.date(2026, 11, 20)
UA = 'Mozilla/5.0 (compatible; mahoyo-boxoffice tracker; +https://finalst11.github.io/mahoyo-boxoffice/)'
FEEDS = [
    'https://news.denfaminicogamer.jp/feed',
    'https://www.cinematoday.jp/index.xml',
    'https://av.watch.impress.co.jp/data/rss/1.0/avw/feed.rdf',
]
TITLE_HINT = re.compile(r'興収|興行収入|動員|突破')
NUMS = r'([\d,]+(?:億[\d,]*)?(?:万[\d,]*)?)'
PATTERNS = [
    # 「公開4日間で」「11月20日(金)～22日(日)の3日間で」「累計…日間」
    ('days', re.compile(r'(?:公開|累計|11月20日)[^。]{0,30}?(\d+)日間[^。]{0,40}?(?:観客)?動員(?:数)?(?:は|が|:)?\s*' + NUMS + r'人[^。]{0,25}?興行収入(?:は|が|:)?\s*' + NUMS + r'円')),
    # 「12月6日時点で観客動員…、興行収入…」
    ('date', re.compile(r'(\d{1,2})月(\d{1,2})日(?:\([^)]{1,4}\))?(?:時点|まで)[^。]{0,30}?(?:観客)?動員(?:数)?(?:は|が|:)?\s*' + NUMS + r'人[^。]{0,25}?興行収入(?:は|が|:)?\s*' + NUMS + r'円')),
]


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    time.sleep(2)
    return data.decode('utf-8', 'replace')


def to_int(s):
    """「256,305」「25万6305」「4億5149万4100」→ 整数；约数（以万/億结尾）返回 None。"""
    s = s.replace(',', '')
    if not s or s.endswith(('万', '億')):
        return None
    total, rest = 0, s
    if '億' in rest:
        a, rest = rest.split('億', 1)
        total += int(a or 0) * 10 ** 8
    if '万' in rest:
        a, rest = rest.split('万', 1)
        total += int(a or 0) * 10 ** 4
    if rest and not rest.isdigit():
        return None
    return total + int(rest or 0)


def text_of(page):
    page = re.sub(r'<script.*?</script>|<style.*?</style>', '', page, flags=re.S)
    t = html.unescape(re.sub(r'<[^>]+>', '', page))
    return unicodedata.normalize('NFKC', t)


def candidates(text, pub_date):
    out = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            if kind == 'days':
                n, a, g = int(m.group(1)), to_int(m.group(2)), to_int(m.group(3))
                day = n
            else:
                mo, d, a, g = int(m.group(1)), int(m.group(2)), to_int(m.group(3)), to_int(m.group(4))
                year = RELEASE.year if mo >= RELEASE.month else RELEASE.year + 1
                try:
                    day = (dt.date(year, mo, d) - DAY0).days
                except ValueError:
                    continue
            if a and g and day >= 1:
                date = DAY0 + dt.timedelta(days=day)
                if pub_date and date > pub_date:  # 截止日期不可能晚于发布日期
                    continue
                out.append((day, a, g))
    return out


def feed_items(xml):
    items = []
    for block in re.findall(r'<(?:item)\b.*?</item>', xml, re.S):
        t = re.search(r'<title[^>]*>(.*?)</title>', block, re.S)
        l = re.search(r'<link[^>]*>(.*?)</link>', block, re.S) or re.search(r'rdf:about="([^"]+)"', block)
        d = re.search(r'<(?:pubDate|dc:date)>(.*?)</(?:pubDate|dc:date)>', block, re.S)
        if not t or not l:
            continue
        title = html.unescape(re.sub(r'<!\[CDATA\[|\]\]>', '', t.group(1))).strip()
        link = html.unescape(re.sub(r'<!\[CDATA\[|\]\]>', '', l.group(1))).strip()
        pub = None
        if d:
            s = d.group(1).strip()
            for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M%z'):
                try:
                    pub = dt.datetime.strptime(s, fmt).astimezone(dt.timezone(dt.timedelta(hours=9))).date()
                    break
                except ValueError:
                    pass
        items.append((title, link, pub))
    return items


def main():
    with open(MILESTONES, encoding='utf-8', newline='') as f:
        text = f.read()
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames
    rows = list(reader)
    seen = []
    if os.path.exists(SEEN):
        with open(SEEN, encoding='utf-8') as f:
            seen = json.load(f)
    seen_set = set(seen)
    n_seen0 = len(seen)

    def latest():
        m = [r for r in rows if r['film'] == 'MAHO' and r['kind'] == 'point' and r['attendance'] and r['gross']]
        m.sort(key=lambda r: int(r['day']))
        return m[-1] if m else None

    added = []
    for feed in FEEDS:
        try:
            items = feed_items(get(feed))
        except Exception as e:
            print('RSS 读取失败', feed, e)
            continue
        for title, link, pub in items:
            if '魔法使いの夜' not in title or not TITLE_HINT.search(title) or link in seen_set:
                continue
            try:
                body = text_of(get(link))
            except Exception as e:
                print('文章读取失败', link, e)
                continue
            seen.append(link)
            seen_set.add(link)
            for day, a, g in sorted(set(candidates(body, pub))):
                top = latest()
                if top and (day <= int(top['day']) or a <= int(top['attendance']) or g <= int(top['gross'])):
                    continue
                if not 1200 <= g / a <= 2600:
                    print('平均票价不合理，跳过', day, a, g)
                    continue
                if any(r['film'] == 'MAHO' and r['day'] == str(day) for r in rows):
                    continue
                dom = re.sub(r'^https?://(www\.)?([^/]+).*$', r'\2', link)
                row = {k: '' for k in fields}
                row.update(film='MAHO', day=str(day), date=(DAY0 + dt.timedelta(days=day)).isoformat(),
                           attendance=str(a), gross=str(g), kind='point',
                           source_note=f'自动抓取（待核对）：{dom} {pub or ""} 转载/引用的官方数字',
                           source_url=link)
                rows.append(row)
                added.append(row)
                print(f'新官方节点：第{day}天 动员 {a:,} 人 票房 {g:,} 日元 ← {title} {link}')

    if len(seen) != n_seen0:
        with open(SEEN, 'w', encoding='utf-8') as f:
            json.dump(seen[-500:], f, ensure_ascii=False, indent=0)
            f.write('\n')
    if not added:
        print('没有新的官方节点')
        return 0
    rows.sort(key=lambda r: (['HF1', 'HF2', 'HF3', 'MAHO'].index(r['film']) if r['film'] in ('HF1', 'HF2', 'HF3', 'MAHO') else 9,
                             r['kind'] == 'final', int(r['day']) if r['day'] else 0))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    with open(MILESTONES, 'w', encoding='utf-8', newline='') as f:
        f.write(out.getvalue())
    status_path = os.path.join(ROOT, 'data', 'status.json')
    status = json.load(open(status_path, encoding='utf-8')) if os.path.exists(status_path) else {}
    status['updated_at'] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).replace(microsecond=0).isoformat()
    status['official_added_at'] = status['updated_at']
    status['last_item'] = {'kind': 'official', 'day': int(added[-1]['day'])}
    with open(status_path, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write('\n')
    gh = os.environ.get('GITHUB_OUTPUT')
    if gh:
        with open(gh, 'a') as f:
            f.write('official=' + '、'.join(f'第{r["day"]}天官方节点' for r in added) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
