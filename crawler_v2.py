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
import re
import sys
import copy
import json
import argparse

from sources import SOURCES, enabled_sources, find
from sources.base import norm_name, is_blocked, SENSITIVE_WORDS, clean_title_suffix

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

# 已下架的源：即使旧 vod.json / vod-<源>.json 里还有数据，也不要再带回来
DROPPED_SOURCES = {'tzqjdy', 'a123tv', 'ncat21'}


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


# 版本/清晰度标签：用于跨源、跨线路的兜底清洗。
# 只要同一部片还有 HD / 正片 / 4K，就绝不能把 TC / 枪版线路留给手机。
# 注意用区分大小写匹配：HDTC / HDTS 必须算低清，但英文单词里的 ts 不算。
_LOW_VERSION_RE = re.compile(r'(?<![A-Z])(?:HD)?(?:TC|TS|CAM)|枪版|抢先版|清晰版|偷录|盗摄')
_HIGH_VERSION_RE = re.compile(r'(?:HD|BD|蓝光|高清|超清|4K|1080P|720P|正片|完整版)', re.I)
_LANG_VERSION_RE = re.compile(r'(?:国语|普通话|粤语|潮汕话|闽南语|原声|中字|中文字幕)', re.I)


def _version_score(text):
    """清晰度评分：HD/正片 +50，TC/枪版 -100，纯集数不计分。"""
    s = (text or '').strip()
    if not s:
        return 0
    if s.isdigit() or re.fullmatch(r'第\s*\d+\s*集', s):
        return 0
    if _LOW_VERSION_RE.search(s):
        return -100
    score = 50 if _HIGH_VERSION_RE.search(s) else 0
    if _LANG_VERSION_RE.search(s):
        score += 2
    return score


def _group_name_score(name):
    """线路名评分。'4K影视' 是站点名不是清晰度，不能因为带 4K 就排到 19 集线路前面。"""
    name = name or ''
    if re.search(r'(影视|影院|视频|资源|网站)', name):
        return 0
    return _version_score(name)


def _line_quality(name, eps):
    """一条线路的综合质量：线路名 + 最好的一集标签。"""
    scores = [_version_score(n) for n, _ in _ep_pairs(eps)]
    return _group_name_score(name) + (max(scores) if scores else 0)


def _ep_pairs(eps):
    """'第01集$url#第02集$url' → [('第01集', 'url'), ...]"""
    out = []
    for p in eps.split('#'):
        if '$' in p:
            name, url = p.split('$', 1)
            if url.startswith('http'):
                out.append((name, url))
    return out


def polish_groups(groups, type_name=''):
    """
    线路质量兜底：
      1. 同一部片只要有一条 HD/正片/4K 线路，就丢掉纯 TC/枪版线路；
      2. 同一条线路里同时有 HD 和 TC 时，丢掉 TC；
      3. 高质量线路排前面，手机默认打开的第一条就是好版本；
      4. 连续剧/动漫/综艺还要看集数：只有 3 集的 HD 线路不应该压过 19 集的完整线路。
    """
    scored = []
    for name, eps in groups:
        pairs = _ep_pairs(eps)
        if not pairs:
            continue
        ep_scores = [_version_score(n) for n, _ in pairs]
        gscore = _group_name_score(name) + (max(ep_scores) if ep_scores else 0)
        scored.append({'name': name, 'pairs': pairs, 'scores': ep_scores, 'score': gscore})

    if not scored:
        return []

    best = max(g['score'] for g in scored)
    if best >= 50:
        scored = [g for g in scored if g['score'] >= 0]

    for g in scored:
        # 线路内混着 TC/HD 时，只留不低清的版本
        if any(s >= 50 for s in g['scores']):
            kept = [(n, u) for (n, u), s in zip(g['pairs'], g['scores']) if s >= 0]
            if kept:
                g['pairs'] = kept

    # 连续剧里，集数明显少于最全线路的高清线路降级但不删除，
    # 避免手机默认打开一条只有 3 集的残缺线路。
    if type_name in ('连续剧', '动漫', '综艺') and scored:
        max_len = max(len(g['pairs']) for g in scored)
        if max_len:
            for g in scored:
                if g['score'] >= 50 and len(g['pairs']) < max_len * 0.6:
                    g['score'] = 0

    # 质量优先，其次集数多的优先；同分保持原顺序
    scored.sort(key=lambda g: (-g['score'], -len(g['pairs'])))
    return [(g['name'], '#'.join(f'{n}${u}' for n, u in g['pairs'])) for g in scored]


def _max_ep_count(item):
    """一条数据里最长线路的集数。"""
    return max((len(_ep_url_set(eps)) for _, eps in split_groups(item)), default=0)


def _looks_broken(item):
    """
    识别早期 a123tv 解析错误留下的数据：整条线路只有一条，集名全是「线路220」。

    这种数据虽然「集数」看起来很多（其实是线路数），但完全不可用；
    不能因为旧数据条数多就拒绝新抓到的正确数据。
    """
    groups = split_groups(item or {})
    if not groups:
        return False
    pairs = _ep_pairs(groups[0][1])
    if not pairs:
        return False
    return all(re.fullmatch(r'线路\d+', name or '') for name, _ in pairs)


def _sync_remarks(type_name, remarks, groups):
    """
    备注里的集数要跟实际剧集数一致。

    很多源的备注更新慢（比如线路里已经 19 集，备注还写「更新第18集」），
    手机会优先显示备注，看起来就像没更新。这里只在「备注集数 < 实际集数」时
    改成「更新至19集」；电影/综艺的其它备注不动。
    """
    if type_name not in ('连续剧', '动漫', '综艺'):
        return remarks
    max_eps = max((len(_ep_url_set(u)) for _, u in groups), default=0)
    if max_eps <= 0:
        return remarks
    text = remarks or ''
    m = re.search(r'\d+', text)
    if not m:
        return text
    if int(m.group(0)) < max_eps:
        return f'更新至{max_eps}集'
    return text


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
            new_q = _line_quality(name, eps)
            for idx, (old_name, old_eps) in enumerate(groups):
                old_urls = _ep_url_set(old_eps)
                old_q = _line_quality(old_name, old_eps)
                if new_urls == old_urls:
                    # 同一批地址只留质量更高的那条，避免 HD 线路被同名 TC 顶掉
                    if new_q > old_q:
                        drop_idx = idx
                        break
                    keep = False
                    break
                if new_urls < old_urls:
                    # 新线路集数少：只有「新的是 HD、旧的是 TC」且覆盖大部分集数时才替换
                    if (new_q >= 50 and old_q < 50
                            and len(new_urls) >= max(3, int(len(old_urls) * 0.6))):
                        drop_idx = idx
                        break
                    keep = False
                    break
                if old_urls < new_urls:
                    # 旧线路集数少：旧的是 HD、新的是 TC 时，保留旧的完整线路
                    if (old_q >= 50 and new_q < 50
                            and len(old_urls) >= max(3, int(len(new_urls) * 0.6))):
                        keep = False
                        break
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
        # 质量优先（HD/正片 > 无标签 > TC/枪版），同质量再按集数降序
        groups = polish_groups(groups, it.get('type_name'))
        if not groups:
            continue
        it['vod_remarks'] = _sync_remarks(
            it.get('type_name'), it.get('vod_remarks'), groups)
        it['vod_play_from'] = '$$$'.join(g[0] for g in groups)
        it['vod_play_url'] = '$$$'.join(g[1] for g in groups)
        out.append(it)
    return out


def clean_and_filter(items):
    """敏感词过滤 + 分类归一化。过滤必须在这里做，不能只放在 Worker。"""
    kept, dropped = [], 0
    for it in items:
        old_name = it.get('vod_name')
        new_name = clean_title_suffix(old_name) or old_name
        if new_name and new_name != old_name:
            print(f'  片名去版本标签: {old_name} → {new_name}')
            it['vod_name'] = new_name
        old_rem = (it.get('vod_remarks') or '').strip()
        new_rem = clean_title_suffix(old_rem)
        if new_rem != old_rem:
            it['vod_remarks'] = new_rem

        # 单源文件也先做一遍线路质量清洗，避免分源订阅里第一条还是 TC
        groups = polish_groups(split_groups(it), it.get('type_name'))
        if groups:
            it['vod_play_from'] = '$$$'.join(g[0] for g in groups)
            it['vod_play_url'] = '$$$'.join(g[1] for g in groups)
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
        it['vod_name'] = clean_title_suffix(it.get('vod_name')) or it.get('vod_name')
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
        it['vod_name'] = clean_title_suffix(it.get('vod_name')) or it.get('vod_name')
        cache[norm_name(it.get('vod_name'))] = it
    return cache


def make_skip(cache, source_key=None, force=None):
    """
    返回一个 skip(name, remarks) 判断函数。

    规则：片名在缓存里、并且备注完全一样 → 跳过（不用请求详情页）。
         备注变了（比如「更新第02集」→「更新第05集」）→ 重抓，否则新剧集永远补不上。

    source_key：只和「同一个源」的旧数据比较。否则新加的源会因为别的源已经
    有同名同备注的片子而被误跳过，永远进不了自己的分源文件。

    force：只重抓这些片名（norm_name 后的集合），其它一律跳过。
           用来在抓取逻辑升级后单独刷新指定片子，不用整站重跑。
    """
    forced = {norm_name(x) for x in (force or [])}

    def skip(name, remarks):
        key = norm_name(name)
        if forced:
            return key not in forced
        old = cache.get(key)
        if not old:
            return False
        if source_key and (old.get('vod_source') or 'a123tv') != source_key:
            return False
        # vod_remarks 可能被合并阶段补成「更新至19集」，源站列表页却只写 1080p 或空。
        # 增量判断必须和「源站原始备注」比，否则同一部片每轮都会被重抓。
        old_remarks = old.get('vod_remarks_src')
        if old_remarks is None:
            old_remarks = old.get('vod_remarks') or ''
        return old_remarks == (remarks or '')
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
        before = len(cache)
        cache = {
            k: v for k, v in cache.items()
            if (v.get('vod_source') or 'a123tv') not in DROPPED_SOURCES
        }
        if len(cache) != before:
            print(f'已丢弃下架源 {", ".join(sorted(DROPPED_SOURCES))} 的 '
                  f'{before - len(cache)} 条缓存')
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
    forced_sources = set()
    for src in sources:
        print(f'== 抓取 {src.key} ({src.name}) ==')
        forced = []
        if args.refresh:
            # 抓取逻辑升级后（例如换了线路选择方法），强制重抓本源缓存里的所有片子
            forced = list((prev_by_source.get(src.key) or {}).keys())
        elif args.force:
            forced = [x.strip() for x in re.split(r'[,，]', args.force) if x.strip()]
        if forced:
            forced_sources.add(src.key)
            print(f'  [{src.key}] 强制重抓 {len(forced)} 条')
        skip = make_skip(prev_by_source.get(src.key) or {}, src.key, force=forced)
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
        prev_by_name = {norm_name(v.get('vod_name')): v for v in prev}
        fresh_keys = {norm_name(it.get('vod_name')) for it in fresh}

        items = []
        for it in fresh:
            key = norm_name(it.get('vod_name'))
            old = prev_by_name.get(key)
            # 源站列表页的原始备注（可能是空），增量判断用它，避免每轮重抓
            raw_remarks = it.get('vod_remarks') or ''
            # 指定片单直接走详情页，拿不到列表页的上映日期等备注，沿用缓存里的
            if old and not raw_remarks.strip():
                old_rem = old.get('vod_remarks') or ''
                if not re.fullmatch(r'\d+\s*个线路', old_rem):
                    it['vod_remarks'] = old_rem
            it['vod_remarks_src'] = raw_remarks
            new_n, old_n = _max_ep_count(it), _max_ep_count(old or {})
            # 本次抓取不完整（比如站点限流）时，不要让少集数覆盖缓存里的多集数。
            # 但旧数据明显是「线路名当集名」的坏数据时，必须让新数据覆盖。
            if (old and old_n > new_n
                    and s.key not in forced_sources
                    and not _looks_broken(old)):
                print(f'  [{s.key}] {it.get("vod_name")} 本次 {new_n} 集 < '
                      f'缓存 {old_n} 集，保留缓存')
                items.append(old)
            else:
                items.append(it)
        items += [v for v in prev
                  if norm_name(v.get('vod_name')) not in fresh_keys]
        if items:
            source_items[s.key] = items

    # 老数据里 vod_source 不是已知源的（或分源文件里漏掉的），兜底带回聚合文件，避免升级时丢片
    covered = {
        (key, norm_name(it.get('vod_name')))
        for key, items in source_items.items()
        for it in items
    }
    for src in SOURCES:
        subset = list(source_items.get(src.key, []))
        if not subset:
            continue
        sub_items = [copy.deepcopy(x) for x in subset]
        kept_s, dropped_s = clean_and_filter(sub_items)
        if not kept_s:
            continue
        merged_s = merge_items(kept_s)
        sub_payload = build_payload(merged_s)
        fn = f'vod-{src.key}.json'

        if args.dry_run:
            print(f'dry-run {fn}：{len(sub_payload["list"])} 条')
            if sub_payload['list']:
                print(json.dumps(sub_payload['list'][0], ensure_ascii=False)[:200])
            continue

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
    p.add_argument('--refresh', action='store_true',
                   help='强制重抓本源缓存里已有的片子（抓取逻辑升级后用）')
    p.add_argument('--force',
                   help='只重抓指定片名，多个用逗号分隔（配合 --pages 扫描列表）')
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