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
import json
import argparse

from sources import enabled_sources, find
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


def merge_items(items):
    """
    跨源合并同一部片：按 (归一化片名, 分类) 归并，线路叠加。
    这样同一部剧在 jsard 和别的源都有时，播放器里会出现多条线路可选。
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
        seen_names, seen_pairs = set(), set()
        groups = []
        for name, eps in it.pop('_groups'):
            # 同名线路加序号，避免播放器里两条一样的名字
            base, n = name, 1
            while name in seen_names:
                n += 1
                name = f'{base}({n})'
            if eps in seen_pairs:
                continue
            seen_names.add(name)
            seen_pairs.add(eps)
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

    all_items = []
    for src in sources:
        print(f'== 抓取 {src.key} ({src.name}) ==')
        try:
            items = src.crawl(pages=args.pages, max_details=args.limit)
        except Exception as e:
            print(f'  [{src.key}] 整体失败，跳过: {e}')
            continue
        print(f'  [{src.key}] 拿到 {len(items)} 条')
        all_items.extend(items)

    kept, dropped = clean_and_filter(all_items)
    merged = merge_items(kept)
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
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', help='只跑指定源，如 jsard')
    p.add_argument('--pages', type=int, default=2, help='每个分类抓几页（默认 2）')
    p.add_argument('--limit', type=int, default=60, help='最多解析多少条详情（默认 60）')
    p.add_argument('--dry-run', action='store_true', help='只打印不写文件')
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
