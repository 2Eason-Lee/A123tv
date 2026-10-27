# -*- coding: utf-8 -*-
"""
jsard / sypfjy 源（两个域名同一套后端，注册一个就够）

实测的取数链路（2026-10 验证）：

  1. 列表：/index.php/ajax/data?mid=1&tid=10&page=1
     返回 JSON，每条的 detail_link 字段就是详情页地址，直接拿来用

  2. 详情页 /voddetail-{id}.html
     页面上有各条线路的链接 /vodplay/{id}-{sid}-1.html，链接文字是线路名

  3. 播放页 /vodplay/{id}-{sid}-{nid}.html
     里面有 player_aaaa = {...} 的 JSON：
        encrypt=2 → url 是 base64 后再 URL 编码，解码两步才拿到 m3u8
        url_next  → 下一集地址，顺着走就能把整部剧集齐

所以一个片子的请求数 = 1 详情 + 每集 1 次，不是整站全量，可控。
"""

import re
import json
import base64
import urllib.parse

from .base import (
    HttpClient, make_item, clean_episodes, abs_url,
    probe_m3u8, quality_score, stream_quality_score,
)


class JsardSource:
    key = 'jsard'
    name = 'FreeOK/新视觉（ajax列表+播放页解码）'
    enabled = True

    host = 'https://www.jsard.com'
    id_base = 2_000_000

    classes = [
        {'type_id': 1, 'type_name': '电影'},
        {'type_id': 2, 'type_name': '连续剧'},
        {'type_id': 3, 'type_name': '综艺'},
        {'type_id': 4, 'type_name': '动漫'},
    ]

    max_lines_movie = 4   # 电影多留几条线路：同一部片常有 TC / HD / 国语 多个版本
    max_lines_series = 2  # 连续剧留两条，避免只剩一条 TC，同时控制请求数
    max_eps = 80          # 每条线路最多抓多少集；76 集连续剧能完整保留
    max_probe_lines = 99  # 探测所有线路，不能在前几条成功后就停

    def __init__(self):
        self.http = HttpClient(referer=self.host)

    # ---------------- 1. 列表 ----------------
    def _list_page(self, tid, page):
        url = f'{self.host}/index.php/ajax/data?mid=1&tid={tid}&page={page}'
        data = self.http.get_json(url)
        if str(data.get('code')) != '1':
            raise RuntimeError(f'列表返回异常: {str(data)[:120]}')
        return data

    # ---------------- 2. 详情页 → 线路列表 ----------------
    def _lines(self, detail_link):
        """
        返回 [(sid, 线路名, 第1集链接), ...]，按页面顺序去重。
        """
        html = self.http.get(self.host + detail_link)
        pairs = re.findall(r'href="(/vodplay/\d+-(\d+)-1\.html)"[^>]*>\s*([^<>]{0,20}?)\s*<', html)
        out, seen = [], set()
        for href, sid, text in pairs:
            if sid in seen:
                continue
            seen.add(sid)
            out.append((sid, (text or f'线路{sid}').strip(), href))
        return out

    # ---------------- 3. 播放页 → 解码出 m3u8 ----------------
    @staticmethod
    def _decode_url(cfg):
        """按 encrypt 字段解码播放地址。"""
        raw = cfg.get('url', '') or ''
        if not raw:
            return ''
        enc = cfg.get('encrypt', 0)
        try:
            if enc == 2:      # base64 + URL 编码
                raw = base64.b64decode(raw + '=' * (-len(raw) % 4)).decode('utf-8', 'ignore')
                return urllib.parse.unquote(raw)
            if enc == 1:      # 仅 URL 编码
                return urllib.parse.unquote(raw)
            return raw        # enc == 0 明文
        except Exception:
            return ''

    def _play_config(self, href):
        """抓播放页并取出 player_aaaa 配置。"""
        html = self.http.get(self.host + href)
        m = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', html)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _episodes(self, first_href, sid, first_cfg=None):
        """
        顺着 link_next 把一条线路的剧集走完。

        注意：配置里的 url_next 是【下一集的播放地址（已编码）】，
        不是下一页地址；要翻页必须用 link_next。
        first_cfg 是探测线路时已经拿到的第一集配置，传进来可以少发一次请求。
        """
        eps = []
        href = first_href
        seen = set()
        cfg = first_cfg
        for _ in range(self.max_eps):
            if not href or href in seen:
                break
            seen.add(href)

            if cfg is None:
                try:
                    cfg = self._play_config(href)
                except Exception as e:
                    print(f'  [{self.key}] 播放页请求失败 {href}: {e}')
                    break
            if not cfg:
                break

            url = self._decode_url(cfg)
            if url:
                nid = str(cfg.get('nid', '') or '')
                name = (cfg.get('note') or '').strip()
                if not name:
                    name = f'第{nid}集' if nid and nid != '1' else '正片'
                eps.append((name, url))

            # 下一页地址：只认 link_next（url_next 是已编码的播放地址）
            nxt = cfg.get('link_next') or ''
            if nxt.startswith('http'):
                nxt = nxt.replace(self.host, '')
            if not nxt.startswith('/'):
                break
            href = nxt
            cfg = None

        return clean_episodes(eps)

    def _probe_line(self, sid, line_name, href):
        """探测一条线路的第一集，拿到质量标签和 m3u8，不整条抓。"""
        try:
            cfg = self._play_config(href)
        except Exception:
            return None
        if not cfg:
            return None
        url = self._decode_url(cfg)
        if not url:
            return None
        note = (cfg.get('note') or '').strip()
        return {
            'sid': sid,
            'name': line_name,
            'href': href,
            'cfg': cfg,
            'url': url,
            'note': note,
            'label': quality_score(line_name),
            'ep': quality_score(note),
        }

    # ---------------- 主流程 ----------------
    def crawl(self, pages=1, max_details=20, skip=None):
        items = []
        seq = 0

        for c in self.classes:
            tid = c['type_id']
            done_cls = 0          # 每个分类单独计数，--limit 是「每分类多少条」
            for page in range(1, pages + 1):
                if max_details and done_cls >= max_details:
                    break
                try:
                    data = self._list_page(tid, page)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 tid={tid} p{page}: {e}')
                    break

                rows = data.get('list', [])
                if not rows:
                    break
                print(f'  [{self.key}] tid={tid} p{page} 列表 {len(rows)} 条')

                for r in rows:
                    if max_details and done_cls >= max_details:
                        print(f'  [{self.key}] {c["type_name"]} 达到 {max_details} 条，换下一分类')
                        break

                    name = r.get('vod_name', '')
                    # 已抓过且备注没变 → 跳过详情页和播放页，省掉最贵的请求
                    if skip and skip(name, r.get('vod_remarks', '')):
                        continue
                    done_cls += 1

                    detail_link = r.get('detail_link', '')
                    if not detail_link:
                        print(f'  [{self.key}] 没有 detail_link，跳过: {name}')
                        continue

                    try:
                        lines = self._lines(detail_link)
                    except Exception as e:
                        print(f'  [{self.key}] 详情失败 {name}: {e}')
                        continue

                    # 分类以每条数据自带的 type_1/type 为准，比固定 tid 更可靠
                    tname = ((r.get('type_1') or {}).get('type_name')
                             or (r.get('type') or {}).get('type_name')
                             or c['type_name'])
                    is_movie = '电影' in tname

                    # 关键：先探测所有线路，按「线路名 + 第一集标签 + 真实码率」排序。
                    # 以前是抓到第一条能播的就停，所以很多片只有一条 TC 线路。
                    candidates = []
                    for order, (sid, line_name, href) in enumerate(lines[:self.max_probe_lines]):
                        cand = self._probe_line(sid, line_name, href)
                        if not cand:
                            continue
                        cand['order'] = order
                        if cand['label'] == 0 and cand['ep'] == 0:
                            cand['stream'] = stream_quality_score(
                                probe_m3u8(self.http, cand['url']))
                        else:
                            cand['stream'] = 0
                        candidates.append(cand)

                    candidates.sort(key=lambda x: (
                        -x['label'], -x['ep'], -x['stream'], x['order']))
                    keep = self.max_lines_movie if is_movie else self.max_lines_series
                    picked = candidates[:keep]

                    groups = []
                    for cand in picked:
                        try:
                            eps = self._episodes(cand['href'], cand['sid'], cand['cfg'])
                        except Exception as e:
                            print(f'  [{self.key}] 播放页失败 {name} sid={cand["sid"]}: {e}')
                            continue
                        if eps:
                            groups.append((cand['name'], eps))

                    if not groups:
                        print(f'  [{self.key}] 没拿到播放地址: {name}')
                        continue

                    item = make_item(
                        vod_id=self.id_base + seq,
                        name=name,
                        type_id=tid,
                        type_name=tname,
                        pic=abs_url(self.host, r.get('vod_pic', '')),
                        remarks=r.get('vod_remarks', ''),
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1
                        print(f'  [{self.key}] ✓ {name} | {groups[0][0]} | {len(groups[0][1])} 集')

        return items