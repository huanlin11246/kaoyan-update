# -*- coding: utf-8 -*-
"""每日考情抓取：从五家官方媒体取最新时政，生成判断题与选择题，发到站点更新频道。

运行环境：GitHub Actions（也可本机手跑）。
  python crawl.py            # 抓取并发布
  python crawl.py --dry      # 只抓不打网络发布

环境变量：
  NTFY                频道地址，默认 https://ntfy.sh/kaoyan_site_updates_v1
  MAX_PER_SOURCE      每个源最多取几条，默认 4
  DAYS                只取最近多少天，默认 30

退出码：0 正常（含无新内容），2 抓到 0 条新内容（工作流据此开 issue）。
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEEN = os.path.join(DATA, "seen.json")
PACKS = os.path.join(DATA, "packs.json")
NTFY = os.environ.get("NTFY", "https://ntfy.sh/kaoyan_site_updates_v1").rstrip("/")
MAX_PER_SOURCE = int(os.environ.get("MAX_PER_SOURCE", "4"))
DAYS = int(os.environ.get("DAYS", "30"))


def fetch(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + i * 3)
    raise last


def text(url, enc="utf-8"):
    return fetch(url).decode(enc, "replace")


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def clean(t):
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.replace("&nbsp;", " ").strip()


def ok_title(t):
    if not (8 <= len(t) <= 60):
        return False
    if re.search(r"(登录|注册|网站地图|关于我们|版权|举报|无障碍|客户端|招聘|English)$", t):
        return False
    return True


def split_date(s):
    s = str(s or "")
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if not m:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if not m:
        return None
    try:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------- 各源 ----------
def src_gov():
    d = json.loads(text("https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json"))
    out = []
    for x in d:
        t = clean(x.get("TITLE", ""))
        if ok_title(t):
            out.append({"title": t, "url": x.get("URL", ""), "date": split_date(x.get("DOCRELPUBTIME")), "src": "中国政府网"})
    return out


def src_qiushi():
    h = text("http://www.qstheory.cn/")
    out = []
    for href, d8, t in re.findall(r'<a[^>]+href="((?:\./)?(\d{8})/[0-9a-f]+/c\.html)"[^>]*>([^<]{6,80})</a>', h):
        t = clean(t)
        if ok_title(t):
            u = href if href.startswith("http") else "http://www.qstheory.cn/" + href.lstrip("./")
            out.append({"title": t, "url": u, "date": split_date(d8), "src": "求是网"})
    return out


def src_cpc():
    h = text("http://cpc.people.com.cn/")
    out = []
    for href, y, md, t in re.findall(r'<a[^>]+href="(http[^"]+/(\d{4})/(\d{4})/[^"]+\.html)"[^>]*>([^<]{6,80})</a>', h):
        t = clean(t)
        if ok_title(t):
            out.append({"title": t, "url": href, "date": "%s-%s-%s" % (y, md[:2], md[2:]), "src": "中国共产党新闻网"})
    return out


def src_people():
    out = []
    for page in ("http://www.people.com.cn/", "http://cpc.people.com.cn/"):
        try:
            h = text(page)
        except Exception:  # noqa: BLE001
            continue
        for href, y, md, t in re.findall(r'<a[^>]+href="(http[^"]*people\.com\.cn[^"]*/(\d{4})/(\d{4})/[^"]+\.html)"[^>]*>([^<]{6,80})</a>', h):
            t = clean(t)
            if ok_title(t):
                out.append({"title": t, "url": href, "date": "%s-%s-%s" % (y, md[:2], md[2:]), "src": "人民网"})
    return out


def src_xinhua():
    out = []
    for page in ("http://www.news.cn/", "http://www.news.cn/politics/"):
        try:
            h = text(page)
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'href="(https?:[^"]*news\.cn[^"]*/(\d{8})/[0-9a-f]+/c\.html)"', h):
            href, d8 = m.group(1), m.group(2)
            seg = h[m.end():m.end() + 800].split("</li>")[0]
            am = re.search(r">([^<]{6,80})</a>", seg)
            if am:
                t = clean(am.group(1))
            else:
                seg = re.sub(r"<img[^>]*>", "", seg)
                seg = re.split(r"<div|</div", seg)[0]
                t = clean(seg)[:60]
                t = re.sub(r'^target="[^"]*">\s*', "", t)
            if ok_title(t):
                out.append({"title": t, "url": href, "date": split_date(d8), "src": "新华网"})
    return out


SOURCES = [("中国政府网", src_gov), ("求是网", src_qiushi), ("中国共产党新闻网", src_cpc), ("人民网", src_people), ("新华网", src_xinhua)]


def collect():
    seen = set(load(SEEN, []))
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - DAYS * 86400))
    fresh = []
    stats = {}
    for name, fn in SOURCES:
        try:
            items = fn()
        except Exception as e:  # noqa: BLE001
            print("[warn] %s 抓取失败：%s" % (name, e))
            stats[name] = -1
            continue
        n = 0
        for it in items:
            if not it["url"] or not it["title"]:
                continue
            if it["date"] and it["date"] < cutoff:
                continue
            h = hashlib.sha1(it["url"].encode("utf-8")).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            it["hash"] = h
            fresh.append(it)
            n += 1
            if n >= MAX_PER_SOURCE:
                break
        stats[name] = n
    return fresh, [it for it in fresh if it.get("date")], stats, seen


def build_pack(items):
    today = time.strftime("%Y-%m-%d")
    items = [it for it in items if it.get("date")]  # 无日期的只当要点用
    names = [n for n, _ in SOURCES]
    qs = []
    for k, it in enumerate(items):
        d = it["date"]
        md = "%d 月 %d 日" % (int(d[5:7]), int(d[8:10]))
        if k % 2 == 0:
            src, answer = it["src"], True
        else:
            # 奇数条换成另一家媒体，考“出处是否对得上”
            src = names[(names.index(it["src"]) + 1 + k) % len(names)]
            answer = src == it["src"]
        stem = "（时政·%s）据%s %s 报道：%s。（　）" % (md, src, d, it["title"])
        note = "该条 %s 由%s公开发布" % (d, it["src"])
        if not answer:
            note += "，题干误标为%s" % src
        qs.append({"path": "politics/shizheng",
                   "q": {"type": "judge", "stem": stem, "answer": answer,
                         "analysis": note + "。原文：" + it["url"]}})
    # 每三条配一道“当日报道”选择题
    group = items
    for i in range(0, max(0, len(group) - 3), 3):
        block = group[i:i + 4]
        if len(block) < 4:
            break
        correct = block[i % len(block)]
        opts = [b["title"] for b in block]
        qs.append({"path": "politics/shizheng",
                   "q": {"type": "choice",
                         "stem": "下列四条中，哪一条是 %s 前后官方媒体公开发布的报道标题？（　）" % block[0]["date"],
                         "options": opts, "answer": opts.index(correct["title"]),
                         "analysis": "正确项来自 %s %s 的报道：%s" % (correct["src"], correct["date"], correct["url"])}})
    hi = []
    for it in items[:8]:
        hi.append({"subject": "政治", "text": "[%s] %s（%s）" % (it["src"], it["title"], it["date"])})
    return {"id": "d" + today.replace("-", ""), "date": today,
            "title": "每日考情 · %d 月 %d 日" % (int(today[5:7]), int(today[8:10])),
            "tags": ["政治", "时政"], "highlights": hi, "items": qs}


def chunk_bytes(s, maxb=3800):
    out, cur, n = [], "", 0
    for ch in s:
        b = len(ch.encode("utf-8"))
        if n + b > maxb and cur:
            out.append(cur)
            cur, n = "", 0
        cur += ch
        n += b
    if cur:
        out.append(cur)
    return out


def publish(pack, packs):
    payload = json.dumps({"generated": time.strftime("%Y-%m-%d"), "packs": packs}, ensure_ascii=False)
    batch = str(int(time.time() * 1000))
    parts = chunk_bytes(payload)
    for k, part in enumerate(parts):
        body = ("KY1|%s|%d|%d|%s" % (batch, k, len(parts), part)).encode("utf-8")
        req = urllib.request.Request(NTFY + "?cache=yes", data=body, method="POST",
                                     headers={"Content-Type": "text/plain; charset=utf-8", "User-Agent": UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status not in (200, 201):
                raise RuntimeError("ntfy HTTP %d" % r.status)
    return len(parts), len(payload)


def main():
    dry = "--dry" in sys.argv
    old = load(PACKS, [])
    fresh, dated, stats, seen = collect()
    print("各源新增：" + "，".join("%s %s" % (k, v) for k, v in stats.items()))
    if not dated:
        print("没有新内容")
        if not dry:
            save(SEEN, sorted(seen)[-4000:])
        return 2
    pack = build_pack(dated)
    if not pack["items"]:
        print("新内容不足，未生成题目")
        return 2
    packs = ([pack] + old)[:12]
    print("生成 %s：%d 条要点 / %d 道题" % (pack["title"], len(pack["highlights"]), len(pack["items"])))
    if dry:
        print(json.dumps(pack, ensure_ascii=False, indent=1)[:1200])
        return 0
    n, size = publish(pack, packs)
    save(PACKS, packs)
    save(SEEN, sorted(seen)[-4000:])
    print("已发布 %d 片，共 %d 字节" % (n, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
