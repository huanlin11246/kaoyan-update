# 考研考情每日自动更新

`crawl.py` 每天从中国政府网、求是网、中国共产党新闻网、人民网、新华网取最新公开报道，
生成判断题与选择题，按站点更新频道格式（`KY1|批次|分片|总数|正文`）发到
`https://ntfy.sh/kaoyan_site_updates_v1`。客户端下次打开就自动并入政治时政。

- `.github/workflows/daily.yml`：每天北京时间 07:30 跑一次；抓到 0 条或脚本异常就开 issue（已有同名 issue 则追加评论）。
- `data/seen.json`：已抓过的链接哈希，避免重复。
- `data/packs.json`：最近 12 个包，发布时整体带上，保证频道里始终有历史。

本机自测：

```bash
python crawl.py --dry          # 只抓不发布
MAX_PER_SOURCE=2 python crawl.py --dry
```

调 `MAX_PER_SOURCE`（每源上限）、`DAYS`（只取最近多少天，默认 30）。
发布端要换频道就设 `NTFY`。

站点自动并入后，客户端会把并集再发回频道；本仓库只负责「有新内容就补进去」。
