# -*- coding: utf-8 -*-
"""
公共工具层：HTTP 请求、播放地址规范化、去重、敏感词过滤。

所有源都只负责「拿到原始数据」，清洗和规范化统一在这里做，
这样以后加新站不用重复写一遍去重逻辑。
"""

import re
import time
import json
import random
import requests

# 统一 UA：手机端 UA 更容易拿到完整页面
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
      'Mobile/15E148 Safari/604.1')

# 敏感词黑名单（在爬虫端过滤，不要指望 Worker）
SENSITIVE_WORDS = ["伦理", "福利", "三级", "风月", "情色", "成人", "伦理片", "无码"]


class HttpClient:
    """带重试、超时、限速的简易客户端。"""

    def __init__(self, referer='', timeout=15, retries=2, delay=0.3):
        self.referer = referer
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        if referer:
            self.session.headers['Referer'] = referer

    def get(self, url, **kwargs):
        """返回文本，失败抛异常（由调用方决定是否吞掉）。"""
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout, **kwargs)
                r.encoding = r.apparent_encoding or 'utf-8'
                time.sleep(self.delay)
                return self._unwrap(r.text)
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt)
        raise RuntimeError(f'请求失败 {url}: {last_err}')

    @staticmethod
    def _unwrap(text):
        """
        有些站会把整页 HTML / JSON 再包一层 JSON 字符串返回
        （"<!DOCTYPE html>\\n<html..." 或 "{\\"code\\":1,...}"），
        不还原的话所有正则和 json.loads 都会失效。这里循环解包。
        """
        s = text.strip()
        for _ in range(3):
            if not (s.startswith('"') and s.endswith('"')):
                break
            try:
                val = json.loads(s)
            except Exception:
                break
            if not isinstance(val, str):
                break
            s = val.strip()
        return s

    def get_json(self, url, **kwargs):
        """返回 JSON。源站偶尔返回 BOM 或前后杂质，这里做一次容错。"""
        text = self.get(url, **kwargs)
        text = text.strip().lstrip('\ufeff')
        try:
            return json.loads(text)
        except Exception:
            # 有些站会包一层 jsonp: callback({...})
            m = re.search(r'\{[\s\S]*\}', text)
            if not m:
                raise
            return json.loads(m.group(0))


def abs_url(base, url):
    """补全 // 开头、/ 开头的图片/链接。"""
    if not url:
        return ''
    url = url.strip()
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return base.rstrip('/') + url
    return url


def norm_name(name):
    """用于跨源去重的名称归一化：去掉季数/年份/空格/标点。"""
    if not name:
        return ''
    s = str(name).lower()
    s = re.sub(r'[\s\-_·:：,，.。!！?？()（）\[\]【】"\'“”‘’]', '', s)
    s = re.sub(r'(第[一二三四五六七八九十\d]+季|season\d+|s\d{1,2})', '', s)
    s = re.sub(r'(19|20)\d{2}', '', s)
    return s


def is_blocked(*texts):
    """命中敏感词就返回 True。"""
    blob = ' '.join(str(t or '') for t in texts)
    return any(w in blob for w in SENSITIVE_WORDS)


def clean_episodes(pairs):
    """
    清洗剧集列表。

    pairs: [(集名, 播放地址), ...]
    规则：
      - 地址必须以 http 开头
      - 同一地址只保留第一次出现（你现在 vod.json 里重复十几次就是这个原因）
      - 集名去空格，空的自动补「第N集」
    """
    seen = set()
    out = []
    for idx, (name, url) in enumerate(pairs):
        if not url or not str(url).startswith('http'):
            continue
        url = str(url).strip().replace(' ', '')
        if url in seen:
            continue
        seen.add(url)
        name = (str(name) if name else f'第{idx + 1}集').strip().replace('$', '').replace('#', '')
        out.append(f'{name}${url}')
    return out


def build_play(groups):
    """
    groups: [(线路名, [集名字符串, ...]), ...]
    返回 (vod_play_from, vod_play_url)，保证两边组数严格一致。
    """
    froms, urls = [], []
    for line_name, episodes in groups:
        if not episodes:
            continue
        line_name = (line_name or f'线路{len(froms) + 1}').replace('$$$', '').replace('$', '')
        froms.append(line_name)
        urls.append('#'.join(episodes))
    return '$$$'.join(froms), '$$$'.join(urls)


def make_item(vod_id, name, type_id, type_name, pic='', remarks='',
              groups=None, source=''):
    """构造一条标准影片数据，组数不一致的直接丢弃。"""
    if not name or not groups:
        return None
    play_from, play_url = build_play(groups)
    if not play_from or not play_url:
        return None
    return {
        'vod_id': vod_id,
        'vod_name': name.strip(),
        'type_id': type_id,
        'type_name': type_name,
        'vod_pic': pic or '',
        'vod_remarks': (remarks or '').strip(),
        'vod_play_from': play_from,
        'vod_play_url': play_url,
        'vod_source': source,
    }


def extract_play(html):
    """
    从详情页 HTML 里抠播放地址，返回 [(线路名, [集, ...]), ...]。

    按可靠性从高到低依次尝试，任何一个成功就返回：
      1. var pp = {"la": [...]}          —— 苹果CMS 常见播放器数据
      2. MacPlayer / player_aaaa 里的 url
      3. 页面里裸的 .m3u8 地址
    """
    groups = []

    # 1) var pp = {...}
    m = re.search(r'var\s+pp\s*=\s*(\{[\s\S]*?\});', html)
    if m:
        try:
            data = json.loads(m.group(1))
            episodes = []
            for idx, line in enumerate(data.get('la', [])):
                if len(line) > 4 and line[4] and str(line[4]).startswith('http'):
                    episodes.append((line[1] if line[1] else f'线路{idx + 1}', line[4]))
            cleaned = clean_episodes(episodes)
            if cleaned:
                groups.append(('线路1', cleaned))
        except Exception:
            pass

    # 2) player 配置里的 url
    if not groups:
        for pattern in (r'"url"\s*:\s*"([^"]+?\.m3u8[^"]*)"',
                        r"url\s*:\s*'([^']+?\.m3u8[^']*)'"):
            m = re.search(pattern, html)
            if m:
                cleaned = clean_episodes([('正片', m.group(1).replace('\\/', '/'))])
                if cleaned:
                    groups.append(('线路1', cleaned))
                    break

    # 3) 裸 m3u8
    if not groups:
        urls = re.findall(r'https?://[^\s"\'<>\\]+?\.m3u8[^\s"\'<>\\]*', html)
        cleaned = clean_episodes([(f'第{i + 1}集', u) for i, u in enumerate(urls)])
        if cleaned:
            groups.append(('线路1', cleaned))

    return groups


def random_ua():
    return random.choice([
        UA,
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    ])


class Source:
    """
    声明式源基类：子类只实现 list_page() 和 play() 两个方法。

    适合「列表页 + 详情页」结构简单、想快速填坑的站（见 sources/stubs.py）。
    比 jsard.py 那种全手写的源少写很多，但灵活性也低一些。

    子类要设：
        key / name / domain / offset（vod_id 段位）/ categories
    """

    enabled = False
    key = ''
    name = ''
    domain = ''
    offset = 0
    categories = []      # [{'type_id': 1, 'type_name': '电影'}, ...]
    delay = 0.3

    def __init__(self):
        self._http = None

    @property
    def http(self):
        """第一次用到时才建连接，这样 stubs.py 先构造再改 domain 也没问题。"""
        if self._http is None:
            self._http = HttpClient(referer=self.domain, delay=self.delay)
        return self._http

    def list_page(self, category, page):
        """返回 [{'vod_name','vod_pic','vod_remarks','detail_link',...}, ...]"""
        raise NotImplementedError(f'{self.key}: 还没实现列表解析')

    def play(self, item):
        """返回 [(线路名, [集字符串, ...]), ...]"""
        raise NotImplementedError(f'{self.key}: 还没实现播放地址解析')

    def crawl(self, pages=1, max_details=20, skip=None):
        items, seq = [], 0
        base = getattr(self, 'id_base', 0) or self.offset

        for c in self.categories:
            done = 0
            for page in range(1, pages + 1):
                if max_details and done >= max_details:
                    break
                try:
                    rows = self.list_page(c, page) or []
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 {c.get("type_name")} p{page}: {e}')
                    break
                if not rows:
                    break

                for r in rows:
                    if max_details and done >= max_details:
                        break
                    # 已抓过且备注没变 → 跳过详情请求
                    if skip and skip(r.get('vod_name', ''), r.get('vod_remarks', '')):
                        continue
                    done += 1
                    try:
                        groups = self.play(r) or []
                    except Exception as e:
                        print(f'  [{self.key}] 详情失败 {r.get("vod_name")}: {e}')
                        continue
                    item = make_item(
                        vod_id=base + seq,
                        name=r.get('vod_name', ''),
                        type_id=c['type_id'],
                        type_name=c['type_name'],
                        pic=r.get('vod_pic', ''),
                        remarks=r.get('vod_remarks', ''),
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1
        return items