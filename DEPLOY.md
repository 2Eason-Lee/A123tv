# 部署到 GitHub + Cloudflare（逐步操作）

> 你的仓库：`https://github.com/2Eason-Lee/A123tv`（分支 `main`）
> 你的 Worker：`https://a123tv-api.eason-lee89750.workers.dev`

## 要传的东西

| 文件 | 动作 |
|---|---|
| `crawler_v2.py` | **替换**（新增分源缓存/线路级去重） |
| `sources/`（整个文件夹） | **新增/替换**（里面有 `fdzys.py` 饭搭子源） |
| `.github/workflows/update.yml` | **替换** |
| `.gitignore` | 新增（可选但建议） |
| `worker.js` | **替换**（`FILE_MAP` 里加了 `/fdzys`） |
| `config.json` | **替换**（新增「🍚 饭搭子影视」站点） |
| `vod.json` / `vod-*.json` | 不用手动传，Action 会自动更新 |

---

# 第一部分：GitHub

## 1. 上传新文件

1. 打开 https://github.com/2Eason-Lee/A123tv
2. 右上角 **Add file** → **Upload files**
3. 把下面这些拖进窗口：
   - `crawler_v2.py`
   - `sources` 文件夹（整个拖进去）
   - `.gitignore`
   - `worker.js`
4. 下方 Commit changes 填 `feat: 多源爬虫 v2` → 点 **Commit changes**

上传完检查一下：仓库根目录应该有 `crawler_v2.py`，点进 `sources` 应该能看到 `base.py`、`a123tv.py`、`jsard.py`、`__init__.py`。
**如果变成了 `sources/sources/base.py` 就是路径错了**，删掉重传。

## 2. 替换 workflow

1. 打开 `.github/workflows/update.yml`
2. 点右上角铅笔图标（Edit this file）
3. `Cmd+A` 全选 → 删除
4. 把本地 `.github/workflows/update.yml` 的内容整段粘进去
5. Commit changes

这个版本比原来的多了两处关键改动：

```yaml
permissions:
  contents: write          # 没这行 Action 可能推不上去
run: python crawler_v2.py --pages 5 --limit 45 --split   # 产出约 700 条 + 分源文件
```

## 3. 打开 Action 的写权限

1. 仓库页 → **Settings**
2. 左侧 **Actions** → **General**
3. 拉到最下面 **Workflow permissions**
4. 选 **Read and write permissions** → **Save**

## 4. 手动跑一次

1. 仓库页 → **Actions** 标签
2. 左侧点 **Update VOD Data**
3. 右边 **Run workflow** → 分支选 `main` → 绿色 **Run workflow**
4. 等 1 分钟刷新，点进这次运行看日志

日志里应该出现：

```
== 抓取 a123tv (A123TV（自研核心）) ==
  [a123tv] ...
  [a123tv] 拿到 180 条
== 抓取 jsard (FreeOK/新视觉（ajax列表+播放页解码）) ==
  [jsard] ✓ xxx | 线路3 | 12 集
  [jsard] 拿到 180 条
----------------------------------------------
原始 360 条 → 敏感词过滤 x 条 → 合并去重后 xxx 条
```

**耗时大约 25~40 分钟**（jsard 要一集一集顺着抓），页面关掉也行，跑完会自动 commit。

跑完回仓库首页，`vod.json` 应该有一条 `Auto update VOD data (...)` 的新提交。

### 这次新增的「饭搭子影视」源

- 代码：`sources/fdzys.py`，已注册进 `sources/__init__.py`，默认启用
- 分源文件：Action 加 `--split` 后会生成 `vod-fdzys.json`
- Worker 路径：`/fdzys`
- 订阅配置：`config.json` 里已经加了「🍚 饭搭子影视」

本地想先单独验证可以跑：

```bash
python3 crawler_v2.py --probe fdzys
python3 crawler_v2.py --source fdzys --pages 1 --limit 4 --split
```

`--limit` 对这个源是「每个分类最多解析多少条」，和 README 里的约定一致。

---

# 第二部分：Cloudflare Worker

## 5. 更新 Worker 代码

1. 打开 https://dash.cloudflare.com
2. 左侧 **Workers & Pages**
3. 点你的 Worker：`a123tv-api`
4. 右上角 **Edit code**（图标是 `</>`）
5. 编辑区 `Cmd+A` 全选 → 删除
6. 把本地 `worker.js` 全文粘进去
7. 右上角 **Deploy** → 确认

`worker.js` 里这两处要和你仓库一致，粘贴后扫一眼：

```js
const BASE_URL = 'https://raw.githubusercontent.com/2Eason-Lee/A123tv/refs/heads/main/';

const FILE_MAP = {
  '': 'vod.json',
  'all': 'vod.json',
  'a123tv': 'vod-a123tv.json',
  'jsard': 'vod-jsard.json',
  'tzqjdy': 'vod-tzqjdy.json',
  'fdzys': 'vod-fdzys.json',
};
```

`/fdzys` 就是靠最后一行读取 `vod-fdzys.json`；如果 Action 没加 `--split`，这个文件不会生成。

## 6. 验证接口

在终端依次跑：

```bash
# 1) 分类
curl -s "https://a123tv-api.eason-lee89750.workers.dev/?ac=list" | head -c 300

# 2) 第一页列表
curl -s "https://a123tv-api.eason-lee89750.workers.dev/?ac=detail&pg=1" | head -c 300

# 3) 搜索
curl -s "https://a123tv-api.eason-lee89750.workers.dev/?wd=造雨" | head -c 300
```

期望结果：

```json
{"code":1,"msg":"成功","page":1,"pagecount":1,"limit":30,
 "total":700,"class":[{"type_id":10,"type_name":"电影"},...],"list":[...]}
```

- `total` 是 0 → GitHub 上 `vod.json` 还没更新成功，回第 4 步看日志
- `code:0` → 点开 Worker 的 **Logs** 看报错
- 刚更新完还是旧数据 → Cloudflare 缓存 5 分钟，等一会儿再试

---

# 第三部分：手机订阅

## 7. 订阅链接

直接用这个（指向 `config.json`）：

```
https://raw.githubusercontent.com/2Eason-Lee/A123tv/main/config.json
```

`config.json` 内容确认是这样，`api` 必须是你现在的 Worker 地址：

```json
{
  "sites": [
    {
      "key": "a123tv_native",
      "name": "流霞 ☁️ A123TV (自研核心)",
      "type": 1,
      "api": "https://a123tv-api.eason-lee89750.workers.dev/",
      "searchable": 1,
      "quickSearch": 1,
      "filterable": 1
    }
  ]
}
```

## 8. 导入

1. 手机打开播放器（影视仓 / TVBox 类）
2. **设置** → **配置地址**
3. 粘贴上面的 `config.json` 链接 → 确定
4. 回首页，等它拉配置
5. 搜索「造雨人」或切到分类页，能出片就通了

---

# 排错对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| Action 报 `Permission denied` / `403` | 没开写权限 | 第 3 步 |
| Action 报 `No module named 'sources'` | `sources/` 路径错了 | 仓库根目录必须直接是 `sources/base.py` |
| Action 成功但 `vod.json` 没变 | 抓取结果为空，脚本主动不覆盖 | 看日志里 `结果为空` 那行 |
| Worker 返回 `total: 0` | raw 里还是旧/空数据 | 等 5 分钟，或直接打开 raw 链接看 |
| Worker 返回 `code:0` | 读 GitHub 失败 | 检查 `DATA_URL` 分支是不是 `main` |
| 手机里有片名但点开黑屏 | m3u8 需要特定 UA/Referer | 浏览器里直接打开该 m3u8 测 |
| 改了代码但行为没变 | Worker 没点 Deploy | 重新 Deploy 一次 |

# 回滚

`vod.json` 每次更新都是一次 commit：

1. 仓库 → `vod.json` → **History**
2. 找到上一个正常的 commit
3. 右边 `...` → **Revert** → 提交

代码回滚同理，找对应 commit revert 即可。
