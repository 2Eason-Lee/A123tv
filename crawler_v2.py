# -*- coding: utf-8 -*-
"""
多源聚合爬虫 v2

用法：
    python3 crawler_v2.py                     # 跑所有启用的源，写 vod.json
    python3 crawler_v2.py --source jsard      # 只跑一个源（调试用）
    python3 crawler_v2.py --pages 1 --limit 20 --dry-run   # 小样本试跑，不落盘
    python3 crawler_v2.py --probe jsard       # 探测源是否还能用

产出：标准的苹果CMS JSON（和你原来 crawler.py 生成的格式一致），
      Cloudflare Worker 那边不用改就能继续读。
"""

import os
import sys
import copy
import json
import argparse

from sources import SOURCES, enabled_sources, find
from sources.base import norm_name, is_blocked, SENSITIVE_WORDS

# 统一分类：不管源站用 1~4 还是 10~13，最后都归到这套
CANONICAL_CLASSES = [
    {'type_id': 10, 'type_name': '电影'},
    {'type_id': 11, 'type_name': '连续剧'},
    {'type_id': 12, 'type_name': '综艺'},
    {'type_id': 13, 'type_name': '动漫'},
]
CLASS_BY_NAME = {c['type_name']: c for c in CANONICAL_CLASSES}
DEFAULT_CLASS = {'type_id': 99, 'type_name': '其他'}

START_ID = 10001          # 保持和旧数据一致的起始 ID
OUT_FILE = 'vod.json'


def canonical(type_name):
    """把源站的分类名映射到统一分类（源站可能叫电视剧、恐怖片、日韩动漫……）。"""
    n = type_name or ''
    if '电视剧' in n or '连续剧' in n or '剧集' in n:
        return CLASS_BY_NAME['连续剧']
    if '动漫' in n or '动画' in n:
        return CLASS_BY_NAME['动漫']
    if '综艺' in n or '真人秀' in n:
        return CLASS_BY_NAME['综艺']
    if '电影' in n or n.endswith('片'):
        return CLASS_BY_NAME['电影']
    return DEFAULT_CLASS


def split_groups(item):
    """拆成 [(线路名, 集列表字符串), ...]，组数不一致的返回空。"""
    froms = item.get('vod_play_from', '').split('$$$')
    urls = item.get('vod_play_url', '').split('$$$')
    if len(froms) != len(urls):
        return []
    return [(f, u) for f, u in zip(froms, urls) if f and u]


def _ep_url_set(eps):
    """把 '第01集$http://...#第02集$http://...' 变成 URL 集合，用来判断新旧剧集覆盖关系。"""
    return {p.split('$', 1)[1] for p in eps.split('#') if '$' in p}


def merge_items(items):
    """
    跨源合并同一部片：按 (归一化片名, 分类) 归并，线路叠加。
    这样同一部剧在 jsard 和别的源都有时，播放器里会出现多条线路可选。

    同名线路去重按「剧集 URL 集合」判断：
      - 集合完全相同      → 重复线路，丢掉
      - 旧集合是新集合子集 → 旧数据（集数少），丢掉
      - 新集合是旧集合子集 → 新数据不完整，保留旧的完整线路
      - 其它              → 不同来源/不同 CDN，保留成两条线路
    """
    merged = {}
    order = []
    for it in items:
        key = (norm_name(it['vod_name']), it['type_name'])
        groups = split_groups(it)
        if not groups:
            continue
        if key not in merged:
            it['_groups'] = groups
            merged[key] = it
            order.append(key)
        else:
            exist = merged[key]
            exist['_groups'].extend(groups)
            if not exist.get('vod_pic'):
                exist['vod_pic'] = it.get('vod_pic', '')
            if not exist.get('vod_remarks'):
                exist['vod_remarks'] = it.get('vod_remarks', '')

    out = []
    for key in order:
        it = merged[key]
        seen_names = set()
        groups = []
        for name, eps in it.pop('_groups'):
            new_urls = _ep_url_set(eps)
            if not new_urls:
                continue

            keep, drop_idx = True, None
            for idx, (_, old_eps) in enumerate(groups):
                old_urls = _ep_url_set(old_eps)
                if new_urls == old_urls or new_urls < old_urls:
                    keep = False
                    break
                if old_urls < new_urls:
                    drop_idx = idx
                    break
            if not keep:
                continue
            if drop_idx is not None:
                dropped_name, _ = groups.pop(drop_idx)
                seen_names.discard(dropped_name)

            # 同名线路加序号，避免播放器里两条一样的名字
            base, n = name, 1
            while name in seen_names:
                n += 1
                name = f'{base}({n})'
            seen_names.add(name)
            groups.append((name, eps))
        if not groups:
            continue
        it['vod_play_from'] = '$$$'.join(g[0] for g in groups)
        it['vod_play_url'] = '$$$'.join(g[1] for g in groups)
        out.append(it)
    return out


def clean_and_filter(items):
    """敏感词过滤 + 分类归一化。过滤必须在这里做，不能只放在 Worker。"""
    kept, dropped = [], 0
    for it in items:
        if is_blocked(it.get('vod_name'), it.get('vod_remarks')):
            dropped += 1
            continue
        c = canonical(it.get('type_name'))
        it['type_id'] = c['type_id']
        it['type_name'] = c['type_name']
        kept.append(it)
    return kept, dropped


def load_cache(path=OUT_FILE):
    """
    读上一次的 vod.json 当缓存。

    返回 {归一化片名: 条目}，用来判断「这部片上次已经抓过、且备注没变」。
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'读取缓存失败，按全量抓取: {e}')
        return {}

    cache = {}
    for it in data.get('list', []):
        if not it.get('vod_play_url'):
            continue
        it.setdefault('vod_source', 'a123tv')   # 旧数据没这个字段，默认算 a123tv
        cache[norm_name(it.get('vod_name'))] = it
    return cache


def load_split_cache(key):
    """
    读 vod-<key>.json（每个源自己的缓存）。

    分源缓存比 vod.json 更准：合并后的 vod.json 里，一条数据可能带着多个源的线路，
    只按 vod_source 分不清哪些线路属于哪个源。分源文件是干净的。
    """
    path = f'vod-{key}.json'
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'读取分源缓存失败 {path}: {e}')
        return {}

    cache = {}
    for it in data.get('list', []):
        if not it.get('vod_play_url'):
            continue
        it.setdefault('vod_source', key)
        cache[norm_name(it.get('vod_name'))] = it
    return cache


def make_skip(cache, source_key=None):
    """
    返回一个 skip(name, remarks) 判断函数。

    规则：片名在缓存里、并且备注完全一样 → 跳过（不用请求详情页）。
         备注变了（比如「更新第02集」→「更新第05集」）→ 重抓，否则新剧集永远补不上。

    source_key：只和「同一个源」的旧数据比较。否则新加的源会因为别的源已经
    有同名同备注的片子而被误跳过，永远进不了自己的分源文件。
    """
    def skip(name, remarks):
        old = cache.get(norm_name(name))
        if not old:
            return False
        if source_key and (old.get('vod_source') or 'a123tv') != source_key:
            return False
        return (old.get('vod_remarks') or '') == (remarks or '')
    return skip


def build_payload(items):
    """生成最终 JSON。vod_id 重新连续编号，避免跨源撞号。"""
    out = []
    for i, it in enumerate(items):
        it['vod_id'] = START_ID + i
        out.append(it)

    classes = list(CANONICAL_CLASSES)
    present = {it['type_name'] for it in out}
    classes = [c for c in classes if c['type_name'] in present]
    if '其他' in present:
        classes.append(DEFAULT_CLASS)

    return {
        'code': 1,
        'msg': '数据成功',
        'page': 1,
        'pagecount': 1,
        'limit': len(out),
        'total': len(out),
        'class': classes,
        'list': out,
    }


def run(args):
    if args.source:
        src = find(args.source)
        if not src:
            print(f'没有这个源: {args.source}')
            return 1
        sources = [src]
    else:
        sources = enabled_sources()

    if not sources:
        print('没有启用的源，检查 sources/__init__.py')
        return 1

    cache = {} if args.fresh else load_cache()
    if cache:
        print(f'聚合缓存 vod.json 里有 {len(cache)} 条')

    # 每个源单独一份缓存：优先读 vod-<源>.json，没有再退回从 vod.json 按 vod_source 过滤。
    # 这样「同名剧在多个源都有」时，不会因为合并后的 vod_source 指向别的源而丢掉本源的线路。
    prev_by_source = {}
    for s in SOURCES:
        prev_by_source[s.key] = {} if args.fresh else load_split_cache(s.key)
    for s in SOURCES:
        if not prev_by_source[s.key]:
            prev_by_source[s.key] = {
                k: v for k, v in cache.items()
                if (v.get('vod_source') or 'a123tv') == s.key
            }

    fresh_by_source = {}
    for src in sources:
        print(f'== 抓取 {src.key} ({src.name}) ==')
        skip = make_skip(prev_by_source.get(src.key) or {}, src.key)
        try:
            items = src.crawl(pages=args.pages, max_details=args.limit, skip=skip)
        except Exception as e:
            print(f'  [{src.key}] 整体失败，跳过: {e}')
            items = []
        print(f'  [{src.key}] 拿到 {len(items)} 条')
        fresh_by_source[src.key] = items

    # 每个源 = 本次抓到的 + 分源缓存里没重抓的。分源文件始终是「本源的完整数据」。
    source_items = {}
    for s in SOURCES:
        fresh = fresh_by_source.get(s.key, [])
        prev = list(prev_by_source.get(s.key, {}).values())
        fresh_keys = {norm_name(it.get('vod_name')) for it in fresh}
        stale = [v for v in prev if norm_name(v.get('vod_name')) not in fresh_keys]
        items = fresh + stale
        if items:
            source_items[s.key] = items

    # 老数据里 vod_source 不是已知源的（或分源文件里漏掉的），兜底带回聚合文件，避免升级时丢片
    covered = {
        (key, norm_name(it.get('vod_name')))
        for key, items in source_items.items()
        for it in items
    }
    legacy = [
        v for v in cache.values()
        if ((v.get('vod_source') or 'a123tv'), norm_name(v.get('vod_name'))) not in covered
    ]

    all_items = [it for items in source_items.values() for it in items] + legacy
    kept, dropped = clean_and_filter(all_items)
    kept_ids = {id(x) for x in kept}

    merged = merge_items(copy.deepcopy(kept))
    payload = build_payload(merged)

    print('-' * 46)
    print(f'原始 {len(all_items)} 条 → 敏感词过滤 {dropped} 条 → 合并去重后 {len(merged)} 条')
    print(f'敏感词表: {",".join(SENSITIVE_WORDS)}')
    for c in payload['class']:
        n = sum(1 for x in payload['list'] if x['type_id'] == c['type_id'])
        print(f'  {c["type_name"]}({c["type_id"]}): {n} 条')

    if not merged:
        print('结果为空，不覆盖 vod.json（防止把线上数据刷没）')
        return 2

    if args.dry_run:
        print('dry-run：不写文件')
        for it in payload['list'][:3]:
            print(json.dumps(it, ensure_ascii=False)[:300])
        return 0

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'已写入 {OUT_FILE}（{os.path.getsize(OUT_FILE) // 1024} KB）')

    # 按源拆成独立文件：手机里就能把每个源当成一个站点单独选
    if args.split:
        for src in SOURCES:
            subset = [x for x in source_items.get(src.key, []) if id(x) in kept_ids]
            if not subset:
                continue
            sub_payload = build_payload(merge_items(copy.deepcopy(subset)))
            fn = f'vod-{src.key}.json'
            with open(fn, 'w', encoding='utf-8') as f:
                json.dump(sub_payload, f, ensure_ascii=False, indent=2)
            print(f'已写入 {fn}（{len(sub_payload["list"])} 条）')

    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', help='只跑指定源，如 jsard')
    p.add_argument('--pages', type=int, default=2, help='每个分类抓几页（默认 2）')
    p.add_argument('--limit', type=int, default=60, help='最多解析多少条详情（默认 60）')
    p.add_argument('--dry-run', action='store_true', help='只打印不写文件')
    p.add_argument('--fresh', action='store_true',
                   help='忽略缓存，全量重抓（默认只抓新增/有更新的）')
    p.add_argument('--split', action='store_true',
                   help='额外按源输出 vod-<源名>.json，手机里可分站点选择')
    p.add_argument('--probe', help='探测某个源的列表/详情是否可解析')
    args = p.parse_args()

    if args.probe:
        src = find(args.probe)
        if not src:
            print(f'没有这个源: {args.probe}')
            return 1
        if hasattr(src, 'probe'):
            src.probe()
        else:
            items = src.crawl(pages=1, max_details=3)
            for it in items:
                print(json.dumps(it, ensure_ascii=False)[:300])
        return 0

    sys.exit(run(args))


if __name__ == '__main__':
    main()
