# 一次性：抓小圆〈ワルプルギスの廻天〉和赛马娘〈新時代の扉〉前 21 天的 mimorin 全天样本（仅分析用，不进网站）
import sys, os, csv, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import update_sample as U
FILMS = [('MADOKA', dt.date(2026, 8, 28), ('ワルプルギス',), 46), ('UMA', dt.date(2024, 5, 24), ('新時代の扉',), 53)]
out = []
for film, d0, keys, ndays in FILMS:
    for k in range(ndays):
        d = d0 + dt.timedelta(days=k)
        try:
            eid = U.find_entry(d)
        except Exception as e:
            print(film, d, 'ERR', e); eid = None
        if not eid:
            print(film, d, 'no entry'); out.append([film, k + 1, d.isoformat(), '', '', '', '', '', 'no entry']); continue
        rows = U.parse_entry(eid) or []
        hit = [r for r in rows if any(x in r[6] for x in keys)]
        last = max(rows, key=lambda h: U.num(h[0]) or 0) if rows else None
        if hit:
            h = hit[0]
            out.append([film, k + 1, d.isoformat(), U.num(h[0]), sum(U.num(x[1]) or 0 for x in hit), sum(U.num(x[2]) or 0 for x in hit), sum(U.num(x[3]) or 0 for x in hit), h[5], f'entry {eid}; rows {len(hit)}; {h[6]}'])
        else:
            out.append([film, k + 1, d.isoformat(), '', '', '', '', '', f'not in top (#{last[0] if last else "?"}={last[1] if last else "?"}) entry {eid}'])
        print(out[-1])
with open(os.path.join(os.path.dirname(__file__), 'compare.csv'), 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['film', 'day', 'date', 'rank', 'sales', 'seats', 'shows', 'wow', 'note']); w.writerows(out)
