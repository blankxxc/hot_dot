"""
新闻热点爬虫 & 智能分类工具
爬取多个主流新闻平台的热点，按内容相似度自动聚类分组。
默认爬取昨日(day-1)新闻，结果保存到 hot_dot/X月X日热点新闻.txt
"""

import requests
import urllib3
from bs4 import BeautifulSoup
import jieba
import json
import re
import sys
import time
import os
from datetime import datetime, date, timedelta
from urllib.parse import quote
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering
from collections import defaultdict

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============ 配置 ============
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 15
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 昨天日期
YESTERDAY = date.today() - timedelta(days=1)
YESTERDAY_STR = f"{YESTERDAY.month}月{YESTERDAY.day}日"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{YESTERDAY_STR}热点新闻.txt")
JSON_FILE = os.path.join(OUTPUT_DIR, f"{YESTERDAY_STR}热点新闻.json")


def make_news(title, desc="", source="", url="", hot_value=None,
              likes=None, reads=None, comments=None, pub_time=""):
    """统一构造新闻条目"""
    item = {"title": title, "desc": desc, "source": source, "url": url}
    if hot_value is not None:
        item["hot_value"] = hot_value
    if likes is not None:
        item["likes"] = likes
    if reads is not None:
        item["reads"] = reads
    if comments is not None:
        item["comments"] = comments
    if pub_time:
        item["pub_time"] = pub_time
    return item


# ============ 爬虫部分 ============

# 国内站点绕过代理直连，避免 Clash 代理导致 SSL 握手失败
NO_PROXY = {"http": None, "https": None}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch(url, **kwargs):
    """统一请求封装，国内站点自动绕过代理"""
    try:
        resp = SESSION.get(url, timeout=TIMEOUT, verify=False,
                           proxies=NO_PROXY, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"  [请求失败] {url[:60]}...  原因: {e}")
        return None


def crawl_baidu_hot():
    """百度热搜"""
    print("[1/6] 正在爬取 百度热搜 ...")
    url = "https://top.baidu.com/board?tab=realtime"
    resp = fetch(url)
    if not resp:
        return []
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for card in soup.select(".category-wrap_iQLoo"):
        title_el = card.select_one(".c-single-text-ellipsis")
        desc_el = card.select_one(".hot-desc_1m_jR")
        hot_el = card.select_one(".hot-index_1Bl1a")
        link_el = card.select_one("a[href]")
        if title_el:
            title = title_el.get_text(strip=True)
            desc = desc_el.get_text(strip=True) if desc_el else ""
            hot_val = hot_el.get_text(strip=True) if hot_el else None
            link = link_el["href"] if link_el and link_el.get("href") else ""
            try:
                hot_val = int(hot_val) if hot_val else None
            except (ValueError, TypeError):
                hot_val = None
            items.append(make_news(title, desc, "百度热搜", url=link, hot_value=hot_val))
    print(f"  百度热搜: 获取 {len(items)} 条")
    return items


def crawl_weibo_hot():
    """微博热搜"""
    print("[2/6] 正在爬取 微博热搜 ...")
    url = "https://weibo.com/ajax/side/hotSearch"
    resp = fetch(url, headers={
        **HEADERS,
        "Referer": "https://weibo.com/",
        "Cookie": "SUB=_2AkMRtjGaf8NxqwFRmP8SyWznaIRyzwzEieKnYHMuJRMxHRl-yT9kqlQbtRB6OkZYjzGHEbCy0oClOJgXCxhbcGUQ-3fD",
    })
    if not resp:
        return []
    items = []
    try:
        data = resp.json()
        for item in data.get("data", {}).get("realtime", []):
            word = item.get("word", "")
            note = item.get("note", "")
            num = item.get("num", None)
            if word:
                title = note or word
                link = f"https://s.weibo.com/weibo?q=%23{quote(word)}%23"
                items.append(make_news(title, word if note else "",
                                       "微博热搜", url=link, hot_value=num))
    except Exception as e:
        print(f"  [解析失败] 微博: {e}")
    print(f"  微博热搜: 获取 {len(items)} 条")
    return items


def crawl_zhihu_hot():
    """知乎热榜"""
    print("[3/6] 正在爬取 知乎热榜 ...")
    url = "https://api.zhihu.com/topstory/hot-lists/total?limit=50"
    resp = fetch(url, headers={
        **HEADERS,
        "x-api-version": "3.0.76",
        "x-app-za": "OS=Web",
    })
    if not resp:
        return []
    items = []
    try:
        data = resp.json()
        for item in data.get("data", []):
            target = item.get("target", {})
            title = target.get("title_area", {}).get("text", "")
            excerpt = target.get("excerpt_area", {}).get("text", "")
            hot_val = target.get("metrics_area", {}).get("text", None)
            link_url = target.get("link", {}).get("url", "")
            if title:
                items.append(make_news(title, excerpt, "知乎热榜", url=link_url,
                                       hot_value=hot_val))
    except Exception as e:
        print(f"  [解析失败] 知乎: {e}")
    print(f"  知乎热榜: 获取 {len(items)} 条")
    return items


def crawl_toutiao_hot():
    """今日头条热榜"""
    print("[4/6] 正在爬取 今日头条热榜 ...")
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    resp = fetch(url)
    if not resp:
        return []
    items = []
    try:
        data = resp.json()
        for item in data.get("data", []):
            title = item.get("Title", "")
            link = item.get("Url", "")
            hot_val = item.get("HotValue", None)
            try:
                hot_val = int(hot_val) if hot_val else None
            except (ValueError, TypeError):
                pass
            if title:
                items.append(make_news(title, "", "今日头条", url=link, hot_value=hot_val))
    except Exception as e:
        print(f"  [解析失败] 头条: {e}")
    print(f"  今日头条: 获取 {len(items)} 条")
    return items


def crawl_163_hot():
    """网易新闻热点"""
    print("[5/6] 正在爬取 网易新闻热点 ...")
    url = "https://m.163.com/fe/api/hot/news/flow"
    resp = fetch(url)
    if not resp:
        return []
    items = []
    try:
        data = resp.json()
        for item in data.get("data", {}).get("list", []):
            title = item.get("title", "")
            desc = item.get("digest", "") or item.get("stitle", "")
            docid = item.get("docid", "")
            link = item.get("url", "") or item.get("skipURL", "")
            if not link and docid:
                link = f"https://www.163.com/dy/article/{docid}.html"
            reply_count = item.get("replyCount", None)
            ptime = item.get("ptime", "")
            if title:
                items.append(make_news(title, desc, "网易新闻", url=link,
                                       comments=reply_count, pub_time=ptime))
    except Exception as e:
        print(f"  [解析失败] 网易: {e}")
    print(f"  网易新闻: 获取 {len(items)} 条")
    return items


def crawl_thepaper_hot():
    """澎湃新闻热榜"""
    print("[6/6] 正在爬取 澎湃新闻 ...")
    url = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
    resp = fetch(url)
    if not resp:
        return []
    items = []
    try:
        data = resp.json()
        hot_list = data.get("data", {}).get("hotNews", [])
        for item in hot_list:
            title = item.get("name", "")
            cont_id = item.get("contId", "")
            link = f"https://www.thepaper.cn/newsDetail_forward_{cont_id}" if cont_id else ""
            likes = None
            comments = None
            pub_time = ""
            try:
                likes = int(item.get("praiseTimes", 0))
            except (ValueError, TypeError):
                pass
            try:
                comments = int(item.get("interactionNum", 0))
            except (ValueError, TypeError):
                pass
            # pubTimeLong 是毫秒时间戳
            ts = item.get("pubTimeLong")
            if ts:
                try:
                    pub_time = datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError, OSError):
                    pass
            if title:
                items.append(make_news(title, "", "澎湃新闻", url=link,
                                       likes=likes, comments=comments, pub_time=pub_time))
    except Exception as e:
        print(f"  [解析失败] 澎湃: {e}")
    print(f"  澎湃新闻: 获取 {len(items)} 条")
    return items


# ============ 日期过滤 ============

def filter_yesterday(all_news):
    """
    尽量只保留昨天的新闻。
    有 pub_time 的按日期过滤；没有 pub_time 的保留（热榜本身基本是近24h内容）。
    """
    yesterday_str = YESTERDAY.strftime("%Y-%m-%d")
    filtered = []
    for item in all_news:
        pt = item.get("pub_time", "")
        if pt and len(pt) >= 10:
            # 有精确日期，检查是否是昨天
            if pt[:10] == yesterday_str:
                filtered.append(item)
            # 不是昨天的跳过
        else:
            # 没有日期信息，保留（热榜默认近期）
            filtered.append(item)
    return filtered


# ============ 文本处理 & 聚类 ============

STOP_WORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 "
    "看 好 自己 这 他 她 它 们 那 些 什么 怎么 如何 为什么 吗 吧 呢 啊 哦 哈 嗯 "
    "被 把 让 从 对 与 向 但 而 或 如果 因为 所以 虽然 可以 已经 还 又 再 更 最 "
    "这个 那个 以及 及 等 之 其 该 每 各 某 中 后 前 里 外 年 月 日 号 时 分 秒 "
    "万 亿 个 第 为 于 将 能 来 多 大 小 新 记者 发布 表示 进行 开始 通过 相关".split()
)


def tokenize(text):
    """jieba 分词 + 去停用词"""
    words = jieba.lcut(text)
    return " ".join(w for w in words if len(w) > 1 and w not in STOP_WORDS)


# ---- 预定义分类关键词（约18个类别，粒度适中） ----
CATEGORIES = {
    "中东局势": [
        "伊朗", "以色列", "巴勒斯坦", "哈马斯", "加沙", "叙利亚", "中东",
        "导弹", "停火", "空袭", "军舰", "舰艇", "古巴", "也门", "胡塞",
    ],
    "中美关系": [
        "中美", "特朗普", "访华", "关税", "贸易战", "301调查", "鲁比奥",
        "经贸磋商", "共识", "中方反对", "美方",
    ],
    "国际其他": [
        "俄罗斯", "乌克兰", "普京", "泽连斯基", "北约", "欧盟", "日本",
        "韩国", "朝鲜", "联合国", "G7", "G20", "NATO", "阿富汗", "塔利班",
        "俄外长", "英国", "法国", "德国", "印度",
    ],
    "国内时政": [
        "习近平", "总理", "国务院", "两会", "人大", "政协", "中央",
        "纪委", "反腐", "法治", "政策", "改革", "依法", "中华民族",
        "外交部", "发言人", "国防", "主权", "定居中国",
    ],
    "台海两岸": [
        "台湾", "台北", "台海", "民进党", "绿营", "蓝营", "郑丽文",
        "绿民代", "大陆", "两岸", "海峡",
    ],
    "消费维权": [
        "315", "3·15", "消费者", "维权", "曝光", "点名", "晚会",
        "漂白", "鸡爪", "造假", "卧底", "查处", "涉事", "食品安全",
        "救援队", "主播", "市监",
    ],
    "社会事件": [
        "警方", "法院", "判决", "刑事", "犯罪", "死亡", "身亡",
        "遇难", "失踪", "事故", "案件", "嫌疑", "强制措施", "不雅",
        "起诉", "民警", "免罚",
    ],
    "住房地产": [
        "房价", "房地产", "土地", "首付", "贷款", "用房", "楼市",
        "新规", "止跌", "收窄", "环比",
    ],
    "教育就业": [
        "高考", "考研", "学生", "老师", "校园", "退休", "就业",
        "老年大学", "岗位", "招人", "鲁迅", "启蒙", "书屋",
    ],
    "财经金融": [
        "股市", "A股", "港股", "美股", "基金", "理财", "银行",
        "GDP", "经济", "金价", "金饰", "黄金", "ETF", "量化",
        "私募", "资金", "涌入", "商业", "市值", "营收",
    ],
    "科技互联网": [
        "AI", "人工智能", "大模型", "ChatGPT", "机器人", "自动驾驶",
        "5G", "6G", "量子", "航天", "苹果", "华为", "小米",
        "芯片", "手机", "技术", "互联网",
    ],
    "新能源汽车": [
        "特斯拉", "比亚迪", "新能源", "电池", "电动车", "极氪",
        "预售", "万公里", "充电", "混动", "汽车",
    ],
    "娱乐文化": [
        "明星", "演员", "导演", "电影", "电视剧", "综艺",
        "歌手", "演唱会", "票房", "颁奖", "奥斯卡", "影帝",
        "恋情", "粉丝", "网红", "博主", "游戏", "新中式",
    ],
    "体育赛事": [
        "足球", "篮球", "NBA", "CBA", "世界杯", "欧冠",
        "中超", "奥运", "冠军", "决赛", "联赛", "F1",
        "赛车", "女足", "亚洲杯", "乒乓", "樊振东",
    ],
    "健康医疗": [
        "医生", "健康", "疾病", "癌症", "肝硬化", "手术",
        "药物", "保健", "致癌", "超标", "掏耳朵", "便血",
        "辅食", "宝宝", "书皮", "伟哥", "茶叶", "咖啡",
    ],
    "天气环境": [
        "天气", "暴雨", "台风", "地震", "洪水", "厄尔尼诺",
        "气候", "高温", "寒潮", "最热",
    ],
    "社会万象": [
        "女孩", "男子", "女子", "妈妈", "爸爸", "哥哥", "妹妹",
        "老板", "含泪", "目送", "参军", "送外卖", "破防", "感动",
        "外国人", "国产车", "邮轮", "翼装", "飞行", "猪蹄", "摊位",
        "马斯克",
    ],
}


def classify_by_keywords(news_item):
    """根据关键词匹配返回分类，要求至少匹配2个关键词或1个长关键词"""
    text = news_item["title"] + " " + news_item.get("desc", "")
    scores = {}
    for category, keywords in CATEGORIES.items():
        matched = [kw for kw in keywords if kw in text]
        # 长关键词(>=3字)匹配1个即可，短关键词需要>=1个
        score = sum(2 if len(kw) >= 3 else 1 for kw in matched)
        if score > 0:
            scores[category] = score
    if scores:
        return max(scores, key=scores.get)
    return "其他"


def sub_cluster(news_list, distance_threshold=0.88):
    """在同一大类内，用 TF-IDF + 层次聚类做细分话题。"""
    if len(news_list) <= 3:
        return [news_list]

    texts = [tokenize(n["title"] + " " + n.get("desc", "")) for n in news_list]
    vectorizer = TfidfVectorizer()
    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return [news_list]
    if tfidf_matrix.shape[1] == 0:
        return [news_list]

    # 过滤零向量行，避免 cosine 距离报错
    import numpy as np
    dense = tfidf_matrix.toarray()
    row_norms = np.linalg.norm(dense, axis=1)
    nonzero_mask = row_norms > 0
    nonzero_indices = np.where(nonzero_mask)[0]
    zero_indices = np.where(~nonzero_mask)[0]

    if len(nonzero_indices) <= 3:
        return [news_list]

    dense_nonzero = dense[nonzero_indices]

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(dense_nonzero)

    groups = defaultdict(list)
    for i, label in enumerate(labels):
        groups[label].append(news_list[nonzero_indices[i]])
    # 零向量的条目归入第一个组
    if len(zero_indices) > 0:
        first_label = labels[0] if len(labels) > 0 else 0
        for idx in zero_indices:
            groups[first_label].append(news_list[idx])
    return list(groups.values())


def cluster_news(all_news):
    """
    两级分类：
    1. 关键词 -> 大类 (~18个)
    2. 大类内若>5条则用 TF-IDF 再细分
    最终目标：15~30 个话题
    """
    if not all_news:
        return {}

    category_groups = defaultdict(list)
    for item in all_news:
        cat = classify_by_keywords(item)
        item["_category"] = cat
        category_groups[cat].append(item)

    # 大类内细分：仅拆分超过5条的大类，且合并单条子话题回大类
    result = {}
    for cat, items in category_groups.items():
        if len(items) > 5:
            sub_groups = sub_cluster(items, distance_threshold=0.88)
            # 把只有1条的子话题合并为"综合"组
            merged = []
            for group in sub_groups:
                if len(group) == 1:
                    merged.extend(group)
                else:
                    topic = pick_topic_name(group)
                    key = f"{cat}/{topic}"
                    if key in result:
                        key = f"{cat}/{topic}_{id(group)}"
                    result[key] = group
            if merged:
                topic = pick_topic_name(merged)
                result[f"{cat}/{topic}"] = merged
        else:
            topic = pick_topic_name(items)
            result[f"{cat}/{topic}"] = items

    return result


def pick_topic_name(group_items):
    """从一组新闻中提取话题关键词标签"""
    all_text = " ".join(item["title"] for item in group_items)
    words = jieba.lcut(all_text)
    freq = defaultdict(int)
    for w in words:
        if len(w) > 1 and w not in STOP_WORDS:
            freq[w] += 1
    top_words = sorted(freq, key=freq.get, reverse=True)[:3]
    return "/".join(top_words) if top_words else "综合"


# ============ 输出 ============

def format_results(groups, all_news):
    """格式化输出"""
    lines = []
    lines.append("=" * 70)
    lines.append(f"  {YESTERDAY_STR} 新闻热点聚合分析报告")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  共爬取 {len(all_news)} 条热点，聚合为 {len(groups)} 个话题")
    lines.append("=" * 70)

    # 按组大小排序
    sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    for rank, (topic_key, items) in enumerate(sorted_groups, 1):
        cat = topic_key.split("/")[0]
        topic_kw = "/".join(topic_key.split("/")[1:])
        sources = set(it["source"] for it in items)
        cross = len(sources)
        heat = "*" * min(cross, 5)

        lines.append("")
        lines.append(f"{'─' * 70}")
        lines.append(f"  #{rank}  [{cat}] {topic_kw}  "
                      f"({len(items)} 条, {cross} 个平台) {heat}")
        lines.append(f"{'─' * 70}")

        for i, item in enumerate(items, 1):
            lines.append(f"  {i}. [{item['source']}] {item['title']}")

            # 统计信息行
            stats = []
            if item.get("hot_value"):
                stats.append(f"热度:{item['hot_value']}")
            if item.get("likes"):
                stats.append(f"点赞:{item['likes']}")
            if item.get("reads"):
                stats.append(f"阅读:{item['reads']}")
            if item.get("comments"):
                stats.append(f"评论:{item['comments']}")
            if item.get("pub_time"):
                stats.append(f"时间:{item['pub_time']}")
            if stats:
                lines.append(f"     {' | '.join(stats)}")

            # 链接
            if item.get("url"):
                lines.append(f"     链接: {item['url']}")

            # 描述（简短）
            if item.get("desc"):
                desc = item["desc"][:80] + ("..." if len(item["desc"]) > 80 else "")
                lines.append(f"     {desc}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  分析完毕")
    lines.append("=" * 70)
    return "\n".join(lines)


# ============ 主流程 ============

def main():
    print("=" * 50)
    print(f"  新闻热点爬虫 - 获取{YESTERDAY_STR}热点")
    print("=" * 50)
    print()

    crawlers = [
        crawl_baidu_hot,
        crawl_weibo_hot,
        crawl_zhihu_hot,
        crawl_toutiao_hot,
        crawl_163_hot,
        crawl_thepaper_hot,
    ]

    all_news = []
    for crawler in crawlers:
        try:
            items = crawler()
            all_news.extend(items)
        except Exception as e:
            print(f"  [异常] {crawler.__name__}: {e}")
        time.sleep(0.5)

    if not all_news:
        print("\n未获取到任何新闻数据，请检查网络连接。")
        return

    print(f"\n共获取 {len(all_news)} 条热点新闻")

    # 日期过滤（有精确时间的才过滤，没有的保留）
    all_news = filter_yesterday(all_news)
    print(f"过滤后保留 {len(all_news)} 条（{YESTERDAY_STR}相关）")

    if not all_news:
        print("过滤后无数据。")
        return

    print("正在聚类分析 ...")

    # 聚类
    groups = cluster_news(all_news)

    # 格式化 & 保存
    report = format_results(groups, all_news)
    print(report)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n结果已保存到: {OUTPUT_FILE}")

    # JSON
    json_data = []
    sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
    for topic_key, items in sorted_groups:
        cat = topic_key.split("/")[0]
        json_data.append({
            "category": cat,
            "topic": topic_key,
            "count": len(items),
            "sources": list(set(it["source"] for it in items)),
            "news": [{k: v for k, v in it.items() if k != "_category"}
                     for it in items],
        })
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已保存到: {JSON_FILE}")


if __name__ == "__main__":
    main()
