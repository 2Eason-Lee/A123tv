# -*- coding: utf-8 -*-
"""
源注册表。

加新源只需要两步：
  1. 在 sources/ 下新建 xxx.py，写一个类，实现 crawl(pages) -> list[dict]
  2. 在下面 SOURCES 里加一行，并把类里的 enabled 改成 True
"""

from .a123tv import A123TVSource
from .jsard import JsardSource
from .tzqjdy import TzqjdySource
from .fdzys import FdzysSource
from .maccms import MacCMSSource
from .html_generic import HtmlGenericSource
from .stubs import HELLO, KPKUANG

SOURCES = [
    A123TVSource(),
    JsardSource(),
    TzqjdySource(),
    FdzysSource(),
    MacCMSSource(),
    HtmlGenericSource(),
] + [HELLO, KPKUANG]


def enabled_sources():
    return [s for s in SOURCES if getattr(s, 'enabled', False)]


def find(key):
    for s in SOURCES:
        if s.key == key:
            return s
    return None