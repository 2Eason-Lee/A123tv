# -*- coding: utf-8 -*-
"""
fdzys.com / 饭搭子影视

取数链路（2026-10 实测）：

  1. 列表页（服务端渲染，翻页用 ?page=N）：
       /movie/all?page=N      电影
       /tv/all?page=N         连续剧
       /zongyi/all?page=N     综艺
       /dongman/all?page=N    动漫
     每张卡片是 div.myui-vodbox-content，里面有详情链接、片名、封面、备注。

  2. 详情页 /tv/{slug} 或 /movie/{slug}
     页面里的 div#playlist{sid} 已经列出「每条线路 × 每一集」的播放页链接，
     线路名在 data-name-for 属性旁边（天堂云 / 无印云 / 优质云……）。

  3. 播放页 /tv/{slug}/{nid}?sid={sid}
     内联 player_aaaa 里有 url，分三种：
       - 直接是 .m3u8                → 直接用（大部分云线路）
       - 是 /share/{hash} 分享页     → 再抓一次分享页，取 var main / const url 里的 m3u8
       - 优酷/爱奇艺等网页地址        → 跳过（TVBox 播不了网页）

  所以一个片子的请求数 = 1 详情 + 探测所有线路 + 每集 1 次播放页（分享页线路每集 2 次）。
  电影保留 4 条线路、短剧 2 条、长剧 1 条；每条线路最多 max_eps 集。
"""

import re
import json
import html as _html
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .base import (
    HttpClient, make_item, clean_episodes, abs_url, probe_m3u8,
    quality_score, stream_quality_score,
    clean_title_suffix as clean_title,
)


def filter_versions(eps):
    """同一条线路里如果同时有 HD 和 TC，丢掉 TC 等低清版本。"""
    if not eps:
        return eps
    scores = [quality_score(name) for name, _ in eps]
    if any(s >= 50 for s in scores):
        kept = [(name, url) for (name, url), s in zip(eps, scores) if s >= 0]
        if kept:
            return kept
    return eps


class FdzysSource:
    key = 'fdzys'
    name = '饭搭子影视'
    enabled = True

    host = 'https://fdzys.com'
    id_base = 60_000_000
    delay = 0.15

    max_lines_movie = 4    # 电影/单集片多留几条线路，避免只抓到一条 TC
    max_lines_series = 2   # 连续剧留两条：既有多线路兜底，又不会把请求数翻太多倍
    max_eps = 80           # 单条线路最多抓多少集
    max_probe_lines = 99   # 探测所有线路；不能再因为「前 5 条都不行」漏掉后面的 HD 线路

    classes = [
        {'type_id': 1, 'type_name': '电影', 'path': 'movie/all'},
        {'type_id': 2, 'type_name': '连续剧', 'path': 'tv/all'},
        {'type_id': 3, 'type_name': '综艺', 'path': 'zongyi/all'},
        {'type_id': 4, 'type_name': '动漫', 'path': 'dongman/all'},
    ]

    # 指定片单：列表页翻不到（或排序靠后）时，也保证这些片子始终在源里。
    # 你点名要的嫁金钗就在这里，每次跑都会重新检查剧集有没有更新。
    seed_urls = [
        'https://fdzys.com/tv/jia-jin-cha/1',
        # 下面几部电影站内都有 TC/HD 多版本，固定复查，避免列表页排到后面后
        # 又被缓存里的 TC 枪版顶掉。
        'https://fdzys.com/movie/gei-a-ma-de-qing-shu',
        'https://fdzys.com/movie/huan-ying-lai-long-can-guan',
        'https://fdzys.com/movie/gong-fu-nv-zu',
        'https://fdzys.com/movie/ba-xian',
    ]

    def __init__(self):
        self.http = HttpClient(referer=self.host, delay=self.delay)
        self._player_cache = {}
        self._seen = set()
        self._tls = threading.local()
        self.workers = 5

    # ---------------- 列表 ----------------
    def _list_page(self, path, page):
        url = f'{self.host}/{path}'
        if page > 1:
            url += f'?page={page}'
        html = self.http.get(url)

        rows = []
        for block in re.split(r'<div class="myui-vodbox-content">', html)[1:]:
            link_m = re.search(
                r'<a[^>]+href="(https://fdzys\.com/(?:tv|movie|zongyi|dongman|duanju)/[^"?#]+)"',
                block,
            )
            if not link_m:
                continue
            detail_link = link_m.group(1)

            title_m = re.search(r'<div class="title">([^<]+)</div>', block)
            if not title_m:
                continue
            name = _html.unescape(title_m.group(1)).strip()
            if not name:
                continue

            pic_m = re.search(r'<img[^>]+data-src="([^"]+)"', block)
            tag_m = re.search(r'<div class="tag text-overflow">([^<]*)</div>', block)

            rows.append({
                'detail_link': detail_link,
                'vod_name': name,
                'vod_pic': abs_url(self.host, pic_m.group(1)) if pic_m else '',
                'vod_remarks': _html.unescape((tag_m.group(1) if tag_m else '')).strip(),
            })
        return rows

    # ---------------- 详情页 ----------------
    def _detail(self, detail_url):
        """
        返回 (片名, 封面, 备注, {sid: (线路名, [(集名, 播放页地址), ...])})。
        """
        html = self.http.get(detail_url)

        name = ''
        title_m = (re.search(r'<h1 class="title_name"[^>]*>([\s\S]*?)</h1>', html)
                   or re.search(r'<h1 class="title"[^>]*>([\s\S]*?)</h1>', html))
        if title_m:
            name = re.sub(r'<[^>]+>', '', title_m.group(1))
            name = re.sub(r'\s*第\s*\d+\s*集.*$', '', name)
            name = _html.unescape(name).strip()
        if not name:
            og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og:
                name = _html.unescape(og.group(1)).strip()
        name = clean_title(name)

        pic = ''
        pic_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if pic_m:
            pic = pic_m.group(1)

        remarks = ''
        box_start = html.find('class="detail-box"')
        if box_start >= 0:
            box_end = html.find('class="vod-content"', box_start)
            box = html[box_start: box_end if box_end > box_start else box_start + 1500]
            rm = re.search(r'(更新至[^<|\s]{1,10}|全\d+集|已完结)', box)
            if rm:
                remarks = rm.group(1)

        # 线路名：老模板 data-name-for="1">天堂云</span>
        #         新模板 <li class="player_name" data-sid="1"><a ...>天堂云<span ...
        names = {}
        for sid, line_name in re.findall(
                r'data-name-for="(\d+)"[^>]*>\s*([^<]+?)\s*</span>', html):
            names[sid] = _html.unescape(line_name).strip()
        for m in re.finditer(r'<li[^>]*data-sid="(\d+)"[^>]*>([\s\S]*?)</li>', html):
            sid, body = m.group(1), m.group(2)
            if sid in names:
                continue
            nm = (re.search(r'class="swiper-slide-text"[^>]*>\s*([^<]+?)\s*<', body)
                  or re.search(r'<span>([^<]+)</span>', body))
            if nm:
                names[sid] = _html.unescape(nm.group(1)).strip()

        # 每条线路的剧集：按 id="playlistXX" 切片，避免串到别的线路
        # 只认本站同一部片的链接，否则页面底部「相关推荐」会被当成剧集。
        detail_path = urllib.parse.urlsplit(detail_url).path
        base_path = '/' + '/'.join([p for p in detail_path.split('/') if p][:2]) + '/'

        lines = {}
        starts = list(re.finditer(r'id="playlist\d+"[^>]*data-sid="(\d+)"[^>]*>', html))
        for idx, m in enumerate(starts):
            sid = m.group(1)
            start = m.end()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else min(len(html), start + 80000)
            body = html[start:end]

            eps = []
            seen_urls = set()
            for href, ep_name in re.findall(
                    r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', body):
                href = abs_url(self.host, _html.unescape(href.strip()))
                if not href.startswith('http') or href in seen_urls:
                    continue
                if not urllib.parse.urlsplit(href).path.startswith(base_path):
                    continue
                # 只认本线路的链接：sid=1 的链接通常不带参数，其它线路带 ?sid=N；
                # 不这样卡死的话，页面改版时会把别的线路/相关推荐混进来。
                link_sid = (urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
                            .get('sid', [None])[0])
                if sid == '1':
                    if link_sid not in (None, '1'):
                        continue
                elif link_sid != sid:
                    continue
                seen_urls.add(href)
                ep_name = re.sub(r'<[^>]+>', '', ep_name)
                ep_name = _html.unescape(ep_name).strip().strip('\t')
                if not ep_name:
                    ep_name = f'第{len(eps) + 1}集'
                elif ep_name.isdigit():
                    ep_name = f'第{int(ep_name):02d}集'
                eps.append((ep_name, href))

            eps = filter_versions(eps)
            if eps and sid not in lines:
                line_name = clean_title(names.get(sid, f'线路{sid}')) or names.get(sid, f'线路{sid}')
                lines[sid] = (line_name, eps)

        return name, pic, remarks, lines

    # ---------------- 播放页 / 分享页 ----------------
    @staticmethod
    def _parse_player(html):
        m = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', html)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))
        except Exception:
            return {}

    def _player(self, play_url):
        if play_url in self._player_cache:
            return self._player_cache[play_url]

        cfg = {}
        try:
            cfg = self._parse_player(self.http.get(play_url))
        except Exception as e:
            print(f'  [{self.key}] 播放页失败 {play_url}: {e}')
        self._player_cache[play_url] = cfg
        return cfg

    def _thread_http(self):
        """并发抓播放页时，每个线程用自己的 session。"""
        h = getattr(self._tls, 'http', None)
        if h is None:
            h = HttpClient(referer=self.host, delay=0.02, timeout=15, retries=1)
            self._tls.http = h
        return h

    @staticmethod
    def _share_m3u8_from(html, share_url):
        m = re.search(
            r'(?:const|let|var)\s+(?:url|main)\s*=\s*["\']([^"\']+?\.m3u8[^"\']*)["\']',
            html,
        )
        if not m:
            m = re.search(r'["\']([^"\']+?\.m3u8[^"\']*)["\']', html)
        if not m:
            return ''
        path = m.group(1).replace('\\/', '/').replace('\\u0026', '&')
        return urllib.parse.urljoin(share_url, path)

    def _share_m3u8(self, share_url):
        """分享页里 var main / const url 才是真正的 m3u8。"""
        try:
            html = self.http.get(share_url)
        except Exception as e:
            print(f'  [{self.key}] 分享页失败 {share_url}: {e}')
            return ''
        return self._share_m3u8_from(html, share_url)

    def _episode_m3u8_with(self, http, play_url):
        try:
            cfg = self._parse_player(http.get(play_url))
        except Exception:
            return ''
        raw = str(cfg.get('url') or '')
        if not raw:
            return ''
        if '.m3u8' in raw:
            return raw
        if '/share/' in raw:
            try:
                return self._share_m3u8_from(http.get(raw), raw)
            except Exception:
                return ''
        return ''

    def _episode_m3u8(self, play_url):
        return self._episode_m3u8_with(self.http, play_url)

    def _m3u8_many(self, play_urls):
        """并发抓多集播放页；连续剧几十集串行抓会非常慢。"""
        if not play_urls:
            return []
        results = [''] * len(play_urls)

        def work(i, url):
            try:
                results[i] = self._episode_m3u8_with(self._thread_http(), url)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=min(self.workers, len(play_urls))) as ex:
            list(ex.map(lambda pair: work(*pair), enumerate(play_urls)))

        failed = [i for i, u in enumerate(results) if not u]
        if failed and len(failed) < len(play_urls):
            for i in failed:
                try:
                    results[i] = self._episode_m3u8(play_urls[i])
                except Exception:
                    pass
        return results

    def _probe_line(self, eps):
        """返回 (类型, 第一集 m3u8)，类型是 direct / share；不可用返回 (None, '')。"""
        if not eps:
            return None, ''
        raw = str(self._player(eps[0][1]).get('url') or '')
        if '.m3u8' in raw:
            return 'direct', raw
        if '/share/' in raw:
            m3u8 = self._share_m3u8(raw)
            return ('share', m3u8) if m3u8 else (None, '')
        return None, ''

    # ---------------- 一部片 ----------------
    def _item(self, detail_url, fallback_name='', fallback_pic='', fallback_remarks='',
              type_name='连续剧'):
        name, pic, remarks, lines = self._detail(detail_url)
        raw_name = name or fallback_name
        name = clean_title(raw_name) or raw_name
        pic = pic or fallback_pic
        remarks = remarks or fallback_remarks
        remarks = clean_title(remarks)
        if not name or not lines:
            print(f'  [{self.key}] 详情页没解析到线路: {detail_url}')
            return None

        # 按版本质量排序：HD / 正片 / 高清的线路优先，只有 TC / 枪版的排最后。
        # 同分保持页面原始顺序，不破坏站点自己的推荐。
        ordered = sorted(
            lines.items(),
            key=lambda kv: (
                -quality_score(kv[1][0]),
                -max((quality_score(n) for n, _ in kv[1][1]), default=0),
            ),
        )

        # 关键：探测「所有」线路，而不是抓到第一条能播的就停。
        # 一个片常有 10+ 条线路，无印云这种可能挂的是 TC，优质云才是 HD；
        # 只看页面顺序就会永远只抓到 TC。
        candidates = []
        for order, (sid, (line_name, eps)) in enumerate(ordered):
            if order >= self.max_probe_lines:
                break
            kind, first_m3u8 = self._probe_line(eps)
            if not kind:
                continue

            label = quality_score(line_name)
            ep_score = max((quality_score(n) for n, _ in eps), default=0)
            stream = 0
            # 标签完全看不出清晰度时，才去读 m3u8 的分辨率/码率。
            # 这样「无印云」和「优质云」都没写 HD/TC 时，也能按真实码率分出高下。
            if label == 0 and ep_score == 0:
                stream = stream_quality_score(probe_m3u8(self.http, first_m3u8))
            candidates.append({
                'name': line_name,
                'eps': eps,
                'm3u8': first_m3u8,
                'kind': kind,
                'order': order,
                'label': label,
                'ep_score': ep_score,
                'stream': stream,
            })

        if not candidates:
            print(f'  [{self.key}] 没拿到可用播放地址: {name}')
            return None

        # 直接 m3u8 > 分享页；显式 HD/正片标签 > 无标签 > TC；再看真实码率和集数。
        candidates.sort(key=lambda c: (
            0 if c['kind'] == 'direct' else 1,
            -c['label'],
            -c['ep_score'],
            -c['stream'],
            -len(c['eps']),
            c['order'],
        ))

        max_line_eps = max(len(c['eps']) for c in candidates)
        # 电影多留几条线路兜底；短剧留两条；76 集以上的长剧只留最好的一条，
        # 否则 2 条 × 150 集 = 300 次请求，Action 会被拖垮。
        if max_line_eps <= 2:
            keep = self.max_lines_movie
        elif max_line_eps <= 40:
            keep = self.max_lines_series
        else:
            keep = 1
        picked = candidates[:keep]

        # 每集播放页并发抓，先探测过的第一集直接复用
        jobs = []
        per_line = []
        for li, c in enumerate(picked):
            eps = c['eps'][:self.max_eps]
            per_line.append([(eps[0][0], c['m3u8'])])
            for idx, (ep_name, play_url) in enumerate(eps):
                if idx > 0:
                    jobs.append((li, idx, ep_name, play_url))

        found = self._m3u8_many([j[3] for j in jobs])
        for (li, idx, ep_name, _), m3u8 in zip(jobs, found):
            if m3u8:
                per_line[li].append((ep_name, m3u8))

        groups = []
        for li, c in enumerate(picked):
            cleaned = clean_episodes(per_line[li])
            if cleaned:
                groups.append((c['name'], cleaned))

        if not groups:
            print(f'  [{self.key}] 没拿到可用播放地址: {name}')
            return None

        print(f'  [{self.key}] ✓ {name} | {groups[0][0]} | {len(groups[0][1])} 集')
        return make_item(
            vod_id=0,               # crawler_v2 会统一重编号
            name=name,
            type_id=0,
            type_name=type_name,
            pic=pic,
            remarks=remarks,
            groups=groups,
            source=self.key,
        )

    # ---------------- 主流程 ----------------
    def crawl(self, pages=2, max_details=60, skip=None):
        items = []
        seq = 0

        def add(item):
            nonlocal seq
            if not item:
                return
            item['vod_id'] = self.id_base + seq
            items.append(item)
            seq += 1

        # 1) 指定片单：不受 skip 影响，保证点了名的片子一定重新检查
        for seed in self.seed_urls:
            base = re.sub(r'/\d+(?:\?.*)?$', '', seed)
            if base in self._seen:
                continue
            self._seen.add(base)
            type_name = '连续剧' if '/tv/' in base else ('电影' if '/movie/' in base else '其他')
            add(self._item(seed, type_name=type_name))

        # 2) 各分类列表
        for c in self.classes:
            done_cls = 0
            consec_skip = 0
            for page in range(1, pages + 1):
                if max_details and done_cls >= max_details:
                    break
                if consec_skip >= 30:
                    print(f'  [{self.key}] {c["type_name"]} 连续 {consec_skip} 条缓存命中，提前结束翻页')
                    break
                try:
                    rows = self._list_page(c['path'], page)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 {c["path"]} p{page}: {e}')
                    break
                if not rows:
                    break
                print(f'  [{self.key}] {c["type_name"]} p{page} 列表 {len(rows)} 条')

                for r in rows:
                    if max_details and done_cls >= max_details:
                        break
                    if consec_skip >= 30:
                        break
                    detail_url = r['detail_link']
                    if detail_url in self._seen:
                        continue
                    if skip and skip(r['vod_name'], r.get('vod_remarks', '')):
                        consec_skip += 1
                        continue
                    consec_skip = 0
                    self._seen.add(detail_url)
                    done_cls += 1

                    add(self._item(
                        detail_url,
                        fallback_name=r['vod_name'],
                        fallback_pic=r.get('vod_pic', ''),
                        fallback_remarks=r.get('vod_remarks', ''),
                        type_name=c['type_name'],
                    ))

        return items

    # ---------------- 调试 ----------------
    def probe(self):
        url = f'{self.host}/tv/all'
        print(f'列表页: {url}')
        rows = self._list_page('tv/all', 1)
        print(f'解析到 {len(rows)} 条')
        for r in rows[:3]:
            print('  ', r)

        seed = self.seed_urls[0]
        print(f'\n详情页: {seed}')
        name, pic, remarks, lines = self._detail(seed)
        print(f'片名: {name} | 备注: {remarks} | 封面: {pic[:80]}')
        for sid, (line_name, eps) in lines.items():
            print(f'  sid={sid} {line_name}: {len(eps)} 集，第一集 {eps[0][1]}')