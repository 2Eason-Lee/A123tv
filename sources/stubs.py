"""
剩下 2 个站的适配器骨架（默认关闭）

这 2 个站的模板和 jsard 不一样，不能套 MacCmsCloneSource，需要各写一段解析。
下面把已经探明的事实写清楚，你（或我）按 TODO 填完就能启用。

探测结果：
  m.hellociqryx6e.com  极光影视
      - Next.js 前端（/_next/...），HTML 里没有播放地址
      - 详情页形如 https://m.hellociqryx6e.com/detail/147455
      - TODO: 打开浏览器 F12 -> Network 找它自己的 JSON 接口（一般形如 /api/...），
              拿到接口后把 list_page / play 填上，比解析 HTML 稳得多

  www.kpkuang.fun      看片狂人
      - nginx + 自定义苹果CMS模板，/api.php 404
      - 分类页形如 /vodtype/1/，有 /rss/index.xml
      - 站点响应很慢，容易超时
      - TODO: 确认播放页是否 /vodplay/{id}-{sid}-{nid}.html，
              如果是，直接继承 sources/jsard.py 的 MacCmsCloneSource，
              只改 domain 和列表页解析（列表用 /vodtype/{tid}/ 翻页）
"""

from .base import Source


class TodoSource(Source):
    """占位：实现 list_page / play 后把 enabled 改 True 即可。"""

    enabled = False

    def list_page(self, category, page):
        raise NotImplementedError(f"{self.key}: 还没实现列表解析")

    def play(self, item):
        raise NotImplementedError(f"{self.key}: 还没实现播放地址解析")


HELLO = TodoSource()
HELLO.key = "hellociqryx6e"
HELLO.name = "极光影视"
HELLO.domain = "https://m.hellociqryx6e.com"
HELLO.offset = 40_000_000
HELLO.categories = []

KPKUANG = TodoSource()
KPKUANG.key = "kpkuang"
KPKUANG.name = "看片狂人"
KPKUANG.domain = "https://www.kpkuang.fun"
KPKUANG.offset = 50_000_000
KPKUANG.categories = []

STUBS = [HELLO, KPKUANG]
