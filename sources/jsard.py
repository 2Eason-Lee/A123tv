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

from .base import HttpClient, make_item, clean_episodes, abs_url


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

    max_lines = 1     # 每部片保留几条线路（多了请求翻倍）
    max_eps = 30      # 每条线路最多抓多少集，防止短剧几百集把时间吃光

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

    def _episodes(self, first_href, sid):
        """
        顺着 link_next 把一条线路的剧集走完。

        注意：配置里的 url_next 是【下一集的播放地址（已编码）】，
        不是下一页地址；要翻页必须用 link_next。
        """
        eps = []
        href = first_href
        seen = set()
        for _ in range(self.max_eps):
            if not href or href in seen:
                break
            seen.add(href)

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

        return clean_episodes(eps)

    # ---------------- 主流程 ----------------
    def crawl(self, pages=1, max_details=20):
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
                    done_cls += 1

                    name = r.get('vod_name', '')
                    detail_link = r.get('detail_link', '')
                    if not detail_link:
                        print(f'  [{self.key}] 没有 detail_link，跳过: {name}')
                        continue

                    try:
                        lines = self._lines(detail_link)
                    except Exception as e:
                        print(f'  [{self.key}] 详情失败 {name}: {e}')
                        continue

                    groups = []
                    tried = 0
                    for sid, line_name, href in lines:
                        # 第一条线路经常是死的/预告，所以多试几条，成功够数就停
                        if len(groups) >= self.max_lines or tried >= self.max_lines + 2:
                            break
                        tried += 1
                        try:
                            eps = self._episodes(href, sid)
                        except Exception as e:
                            print(f'  [{self.key}] 播放页失败 {name} sid={sid}: {e}')
                            continue
                        if eps:
                            groups.append((line_name, eps))

                    if not groups:
                        print(f'  [{self.key}] 没拿到播放地址: {name}')
                        continue

                    # 分类以每条数据自带的 type_1/type 为准，比固定 tid 更可靠
                    tname = ((r.get('type_1') or {}).get('type_name')
                             or (r.get('type') or {}).get('type_name')
                             or c['type_name'])

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
