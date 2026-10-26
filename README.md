# A123TV 多源骨架说明

## 数据流

```
sources/*.py  ──抓取──▶  crawler_v2.py（清洗/合并/编号）  ──▶  vod.json
                                                              │
                                                    GitHub 仓库（定时 Action 提交）
                                                              │
                                          Cloudflare Worker 读取 raw 并转成标准接口
                                                              │
                                              手机播放器导入 config.json 订阅
```

## 目录

| 文件 | 作用 |
|---|---|
| `sources/base.py` | 公共层：HTTP 客户端、HTML/JSON 解包、剧集去重、敏感词、标准结构构造 |
| `sources/jsard.py` | 已跑通的源：ajax 列表 + 播放页解码（jsard / sypfjy 同一后端） |
| `sources/tzqjdy.py` | 飘零影院：HTML 列表 + 详情页线路 + 播放页抠 m3u8 |
| `sources/fdzys.py` | 饭搭子影视：HTML 列表 + 详情页线路 + 播放页/分享页取 m3u8 |
| `sources/maccms.py` | 通用苹果CMS 源，站方 `/api.php/provide/vod/` 没关时直接用 |
| `sources/html_generic.py` | 纯 HTML 站模板（tv.tzqjdy.com、kpkuang.fun 这类） |
| `sources/__init__.py` | 源注册表，加源只改这里 |
| `crawler_v2.py` | 调度器：跑所有启用的源 → 过滤 → 合并 → 写 vod.json |
| `crawler.py` | 旧版单源爬虫，先留着，确认 v2 稳定再删 |

## 常用命令

```bash
# 小样本试跑，不覆盖线上 vod.json
python3 crawler_v2.py --source jsard --pages 1 --limit 2 --dry-run

# 正式跑：增量模式（默认）。已抓过且备注没变的片子直接跳过
python3 crawler_v2.py --pages 5 --limit 45 --split

# 强制全量重抓（第一次部署、或怀疑数据有问题时用）
python3 crawler_v2.py --pages 5 --limit 45 --split --fresh

# 只跑某个源
python3 crawler_v2.py --source jsard --pages 3 --limit 30
```

`--limit` 是**每个分类**的详情条数，不是总数。

`--split` 会额外输出 `vod-a123tv.json` / `vod-jsard.json` / `vod-tzqjdy.json` / `vod-fdzys.json`，配合 Worker 的 `/a123tv`、`/jsard`、`/tzqjdy`、`/fdzys` 路径，手机里就能分站点选。

## 增量模式怎么判断

| 情况 | 行为 |
|---|---|
| 缓存里没有这个片名 | 抓详情 |
| 有片名、备注完全一样 | 跳过（省掉详情+播放页请求） |
| 有片名、备注变了（更新第02集 → 第05集） | 重抓，补新剧集 |

缓存就是上一次的 `vod.json`。所以第一次跑是全量（25~40 分钟），之后每 6 小时只需要 1~3 分钟。

> 新增：如果目录里有 `vod-<源>.json`（`--split` 生成的分源文件），增量判断会优先用**对应源自己的缓存**。
> 这样同一部剧在多个源都有时，不会因为 `vod.json` 里 `vod_source` 指向别的源而丢掉本源的线路。
> 合并时按「剧集 URL 集合」去重：短的旧线路会被长的覆盖，不同 CDN 的线路会保留成两条。


## 加一个新源（三步）

1. 先判断这个站有没有标准接口：

```bash
curl -sS -m 15 "https://站点/api.php/provide/vod/?ac=list" | head -c 300
```

- 返回 `{"code":1,"class":[...],"list":[...]}` → 用 `maccms.py`，填 `host` / `api` 就行
- 返回 `closed` → 接口被关，走 HTML 路线（`jsard.py` 或 `html_generic.py`）
- 返回 404 / HTML → 不是苹果CMS，用 `html_generic.py` 模板

2. 复制对应模板改成具体站点，`key` 换成唯一名字，`id_base` 换一个没被占用的段位
   （现用：jsard = 2000000，maccms = 9000000，html 模板 = 3000000，tzqjdy = 30000000，fdzys = 60000000）

3. 在 `sources/__init__.py` 的 `SOURCES` 里加一行，`enabled = True`

## 三条不能破的规则

1. `vod_play_from` 用 `$$$` 拆出的组数 == `vod_play_url` 用 `$$$` 拆出的组数
2. 组内剧集用 `#` 分隔，每集 `名称$地址`；同一地址只能出现一次
3. `vod_id` 全局唯一，由 `crawler_v2.py` 统一重编号

## 关于敏感词

过滤放在 `crawler_v2.py`（爬虫端），不要只放在 Worker。
因为 `vod.json` 是公开的 raw 文件，Worker 里过滤挡不住直接拉 JSON 的人。

## 已知坑（都已在代码里处理）

- **整页被包成 JSON 字符串**：站方返回 `"<!DOCTYPE html>\n<html..."`，`base.py` 的 `_unwrap()` 循环解包
- **播放地址加密**：`player_aaaa` 里 `encrypt=2` 是 base64 + URL 编码，要解两层
- **`url_next` 不是下一页**：它是下一集的播放地址；翻页要用 `link_next`
- **第一条线路经常是死的**：`jsard.py` 会多试几条线路，成功够数才停
