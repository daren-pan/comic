# copymanga —— 拷貝漫畫（copy4000.com）

公开 JSON API 站点，匿名可读（无需登录 / Cookie / 签名）。**学习用途受控源**：默认低频
（`crawl_interval_seconds=3600`）+ 受限样本（列表单次只扫 `MAX_PAGE=1` 页 = 20 部）。

## 接口

| 用途 | 方法与路径 | 关键参数 | 返回 |
|---|---|---|---|
| 列表（最近更新） | `GET /api/v3/comics` | `limit`、`offset`、`ordering`、`theme` | `{total, list[], limit, offset}` |
| 搜索 | `GET /api/v3/search/comic` | `q`、`limit`、`offset` | 同上 |
| 详情 | `GET /api/v3/comic2/{path_word}` | `platform=1` | `{is_banned, is_lock, is_login, is_vip, is_mobile_bind, comic{}, popular, groups{}}` |
| 分组章节 | `GET /api/v3/comic/{path_word}/group/{group}/chapters` | `limit`、`offset` | 同上 |
| 章节内页 | `GET /api/v3/comic/{path_word}/chapter2/{uuid}` | `platform=1` | `results.chapter.contents[].url` |

- **站点** `https://copy4000.com`（作品页 `/comic/{path_word}`）；**API** `https://api.copy4000.com`（**与站点不同域**）。
- `ordering`：`-datetime_updated`（默认）/ `datetime_updated` / `-popular`；`theme=<path_word>` 只取某题材（如 `gedou`）。
- **分页与 limit**：列表/搜索用 `limit` + `offset`，`total` 给总数；分组章节 `limit=500` 可用、`limit=1000`
  **直接返回空** —— 适配器按 500 一页累加（`CHAPTER_PAGE_SIZE`），并有 `MAX_CHAPTERS=3000` 硬上限防异常数据拖死一次详情抓取。

### 请求头

| 头 | 值 | 说明 |
|---|---|---|
| `User-Agent` | 桌面 Chrome UA | **必须**，缺失会被拒 |
| `Accept` | `application/json, text/plain, */*` | |
| `Referer` / `Origin` | `https://copy4000.com/` | |
| `version` | `2024.06.20` | 前端自报版本；带上可避免落到旧版响应 |
| `platform` / `region` | `1` / `1` | |
| `Accept-Language` | `zh-Hans` | **只改界面文案**，作品名仍为繁体（见「已知坑」） |

### 成功判定

统一响应体 `{"code": 200, "message": "请求成功", "results": {...}}`。⚠️ **HTTP 状态码不可信**：参数非法时返回的是非标
**HTTP 210**（body 里 `code: 210`）；判定一律看 **body 的 `code == 200`**，`_api_get` 在 `code != 200` 时抛异常（带 message），把源站报错原样带进日志。

## 图片

- **图床是分片域名 `s?.mangafunb.fun`**：分片形如 `sa`…`sz`、`s0`，同一部作品的封面与正文图落在同一分片
  （由作品路径散列得出）；分片可能新增、无法穷举 → `image_hosts` 用**通配一级子域** `*.mangafunb.fun`（见 `images/transfer._host_allowed`）。
- 图片**明文直出、无签名、无 Referer 限制**；`fetch_source_page_urls` 理论上用不上但仍覆写 —— 万一分片迁移，
  库里登记的旧域名会 404，重拉即可拿到新域名（带章级缓存，同章多页只请求一次）。
- **封面 / 正文图地址一律原样入库，不做改写**（不剥后缀取"原图"）：源站封面形如
  `{id}.{原图扩展名}.{缩略规格}.{缩略图格式}`（如 `1788672090.jpeg.328x422.jpg`）。后缀不是可替换的 resize 参数
  （图床上只有基址与精确的 `.328x422.jpg`，其它规格一律 404）；剥离要按段拆 URL，留错扩展名（缩略图**恒输出 `.jpg`**）
  就整张 404。正文图本就没剥过（`.c1500x.jpg` 为源站定的画质平衡）；历史"剥过后缀"的残留地址需重新采集/导入纠正。

## 模型映射

| 源站 | 项目 |
|---|---|
| 作品 `path_word`（字符串，非数字、非 `uuid`） | `comic`（`source_comic_id`） |
| 所选分组下的每个 chapter（`index` 0 起连续） | `chapter`，`chapter_no = index + 1` |
| `contents[].url` | `page`（`source_url`，入库不下载） |

### 分组怎么选

站点把同一部作品按来源拆成多个组：`default`（默認/連載）、`tankobon`（单行本）、`karapeji`（全彩版）。**只收一个组**
（`default` 优先，缺失/为空时退化为章节最多的组）：组间章节编号语义不同，混收会让同一章出现两次、`chapter_no` 冲突。
`chapter_no` 直接取源站 `index + 1`，**不做标题正则解析** —— `default` 组里也有「第1卷」这类卷标题，正则会取错序号。

## 限流策略

- 默认 `priority=backup`、`crawl_interval_seconds=3600`（1 小时一轮）。
- `MAX_PAGE=50`：列表翻页安全阀（仅全量/首采触达）；增量模式按时间窗口边界翻页，翻到某页全在窗口外即停（与 mangadex/zaimanhua 同一口径）。
- `_api_get` 重试 3 次、退避 0.8s×n；无并发请求。

## 已知坑

1. **源站是繁体（zh-hant）**，`Accept-Language: zh-Hans` 只改界面文案、**不改作品名**：`comic.name` 是繁体，
   简繁两种写法都在 `comic.alias` 里。**作品判重刻意不做繁简折叠**：繁体（港台译本）与简体（大陆译本）是不同
   译本、进度往往不同 → **各占一行、各记进度**（判重只看 `(源, 源作品 ID)`），本源的《電鋸人》与别源的
   《电锯人》**不会合并**，属预期行为；适配器不做语言处理，标题原样透出。
   - **标签归一仍做繁转简**（`taxonomy` 查表前折叠字形 → `格鬥`→`格斗`→「动作」，未命中的繁体标签回落简体写法）—— 那是"概念归一"，与"作品是不是同一部"无关；
   - 指纹（`fingerprint.build_fingerprint`）**不参与判重**，只作"可能重复"的观测标记，同样不做繁简折叠；历史行指纹若为旧规则，跑 `tools/rebuild_fingerprint.py` 对齐。
2. **`groups` 在 `results` 层级**，不在 `comic` 里；组对象字段叫 **`path_word`**（不是 `path`），且组内**不含**
   章节数组，章节必须另请求 group 端点。
3. **列表行的 `theme` 恒为空数组**，列表阶段拿不到标签/分类，只能靠详情补齐。
4. **`datetime_updated` 只到「天」**（`YYYY-MM-DD`，无时分秒）→ 增量窗口按**日期**比较
   （`item.date() >= since.date()`）；按绝对值 `>` 比较会漏掉当天已更新的作品。
5. **`restrict`（`一般向/擦邊級/裸露級`）不是 `is_lock`**：它是内容分级，非付费/锁定。按项目约定
   `restricted` 只认 `is_lock`，故**不**按 `restrict` 过滤 —— 站点含 R18 分区，要不要按分级过滤是产品
   决策，需要时在 `fetch_comic_detail` 加一条判据（建议先讨论，别默默改语义）。
6. **站点没有数字 ID**：作品标识就是 `path_word`（形如 `dianjuren`、`19du`、全大写的
   `HUANGNVZIYIZHANFANGDEKUANGHUA`）。`parse_comic_ref` 只认 `copy4000.com` 链接与裸 `path_word`，其它域名一律拒绝。
7. **`details` 里的 `is_login` / `is_vip` / `is_banned` 不能当"不可读"** —— 与其它源同口径，真正读不读
   得了由 `scheduling/ondemand._probe_readable` 实测一章决定。

## 样例与测试

无独立 `fixtures/` 目录：样例响应（列表 / 详情 / 分组章节 / 章节内页）内联在
`crawler-service/tests/test_copymanga_adapter.py`，与 `weebcentral` 同一写法（离线、不联网）。
