# -*- coding: utf-8 -*-

from .jsard import JsardSource
from .fdzys import FdzysSource
from .kvm import KvmSource
from .maccms import MacCMSSource
from .html_generic import HtmlGenericSource
from .stubs import HELLO, KPKUANG

SOURCES = [
    JsardSource(),
    FdzysSource(),
    KvmSource(),
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