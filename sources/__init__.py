# -*- coding: utf-8 -*-
"""
源注册表。

加新源只需要两步：
  1. 在 sources/ 下新建 xxx.py，写一个类，实现 crawl(pages) -> list[dict]
  2. 在下面 SOURCES 里加一行，并把类里的 enabled 改成 True
"""

from .a123tv import A123TVSource
from .jsard import JsardSource
from .maccms import MacCMSSource
from .html_generic import HtmlGenericSource
from .stubs import STUBS

# 顺序就是抓取顺序；靠前的源优先级更高（合并时线路排在前面）
SOURCES = [
    A123TVSource(),         # 已启用：原来的自研核心，720 条主力
    JsardSource(),          # 已启用：ajax 列表 + 播放页解码
    MacCMSSource(),         # 未启用：确认站方 api.php 可用后填 host/api 再开
    HtmlGenericSource(),    # 未启用：模板，复制成具体站点再开
] + STUBS                   # 未启用：剩下 3 个站的占位骨架（tzqjdy / hello / kpkuang）


def enabled_sources():
    return [s for s in SOURCES if getattr(s, 'enabled', False)]


def find(key):
    for s in SOURCES:
        if s.key == key:
            return s
    return None
