"""
公众号少粉爆文爬虫
基于搜狗微信搜索，按 day-1 热点分类关键词搜索公众号文章，
筛选出可能的"少粉爆文"（非大号发布的热点文章）。
结果保存到 hot_dot/X月X日公众号爆文.txt 和 .json
"""

import requests
import urllib3
from bs4 import BeautifulSoup
import json
import re
import sys
import time
import os
from datetime import datetime, date, timedelta

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============ 配置 ============
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://weixin.sogou.com/",
}
TIMEOUT = 15
NO_PROXY = {"http": None, "https": None}
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

YESTERDAY = date.today() - timedelta(days=1)
YESTERDAY_STR = f"{YESTERDAY.month}月{YESTERDAY.day}日"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{YESTERDAY_STR}公众号爆文.txt")
JSON_FILE = os.path.join(OUTPUT_DIR, f"{YESTERDAY_STR}公众号爆文.json")

# 大号黑名单 —— 这些是粉丝量极大的头部号，排除后留下的更可能是少粉爆文
BIG_ACCOUNTS = {
    "人民日报", "新华社", "央视新闻", "环球时报", "中国新闻网",
    "澎湃新闻", "新京报", "南方都市报", "界面新闻", "第一财经",
    "每日经济新闻", "21世纪经济报道", "中国经济周刊",
    "财新网", "三联生活周刊", "新周刊", "Vista看天下",
    "虎嗅", "36氪", "钛媒体", "极客公园", "量子位",
    "丁香医生", "丁香园", "果壳", "知乎日报",
    "十点读书", "洞见", "有书", "夜听",
    "GQ实验室", "新世相", "咪蒙",
    "占豪", "牛弹琴", "侠客岛", "团结湖参考",
    "人民网", "光明日报", "经济日报", "中国青年报",
    "北京日报", "解放日报", "新民晚报",
    "腾讯新闻", "网易新闻", "搜狐新闻", "凤凰网",
    "观察者网", "环球网", "参考消息",
}

# ============ 分类关键词（与 news_hot_crawler 对齐） ============
CATEGORIES = {
    "中东局势": {
        "search_queries": ["中东局势", "伊朗以色列", "加沙冲突"],
        "keywords": ["伊朗", "以色列", "巴勒斯坦", "哈马斯", "加沙", "叙利亚",
                     "中东", "导弹", "停火", "空袭", "也门", "胡塞"],
    },
    "中美关系": {
        "search_queries": ["中美关系", "特朗普关税", "中美贸易"],
        "keywords": ["中美", "特朗普", "访华", "关税", "贸易战", "鲁比奥",
                     "经贸磋商", "美方"],
    },
    "国际其他": {
        "search_queries": ["俄乌冲突", "国际局势"],
        "keywords": ["俄罗斯", "乌克兰", "普京", "泽连斯基", "北约", "欧盟",
                     "日本", "韩国", "联合国"],
    },
    "国内时政": {
        "search_queries": ["时政要闻", "政策改革"],
        "keywords": ["国务院", "两会", "人大", "政协", "中央", "纪委", "反腐",
                     "改革", "外交部"],
    },
    "消费维权": {
        "search_queries": ["315曝光", "消费维权", "食品安全曝光"],
        "keywords": ["315", "3·15", "消费者", "维权", "曝光", "点名", "晚会",
                     "造假", "卧底", "查处", "食品安全"],
    },
    "社会事件": {
        "search_queries": ["社会热点事件", "案件通报"],
        "keywords": ["警方", "法院", "判决", "犯罪", "死亡", "事故", "案件",
                     "起诉"],
    },
    "住房地产": {
        "search_queries": ["楼市新政", "房价走势"],
        "keywords": ["房价", "房地产", "首付", "贷款", "楼市", "止跌"],
    },
    "教育就业": {
        "search_queries": ["教育改革", "就业招聘"],
        "keywords": ["高考", "考研", "学生", "老师", "校园", "就业"],
    },
    "财经金融": {
        "search_queries": ["A股行情", "黄金投资", "经济形势"],
        "keywords": ["股市", "A股", "基金", "银行", "GDP", "经济", "黄金"],
    },
    "科技互联网": {
        "search_queries": ["AI人工智能", "科技新品发布"],
        "keywords": ["AI", "人工智能", "大模型", "机器人", "华为", "小米", "芯片"],
    },
    "新能源汽车": {
        "search_queries": ["新能源汽车", "电动车测评"],
        "keywords": ["特斯拉", "比亚迪", "新能源", "电池", "电动车", "充电"],
    },
    "娱乐文化": {
        "search_queries": ["娱乐圈热点", "影视综艺"],
        "keywords": ["明星", "演员", "电影", "电视剧", "综艺", "歌手",
                     "演唱会", "票房"],
    },
    "体育赛事": {
        "search_queries": ["体育赛事", "CBA NBA"],
        "keywords": ["足球", "篮球", "NBA", "CBA", "冠军", "决赛", "联赛"],
    },
    "健康医疗": {
        "search_queries": ["健康养生", "医疗科普"],
        "keywords": ["医生", "健康", "疾病", "癌症", "手术", "药物", "保健"],
    },
    "社会万象": {
        "search_queries": ["社会百态", "暖心故事"],
        "keywords": ["女孩", "男子", "女子", "感动", "破防"],
    },
}


def fetch(url, **kwargs):
    """统一请求封装"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                           verify=False, proxies=NO_PROXY, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"  [请求失败] {url[:60]}...  原因: {e}")
        return None


def parse_sogou_articles(html):
    """解析搜狗微信搜索结果页"""
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    for li in soup.select("ul.news-list > li"):
        title_el = li.select_one("h3 a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")
        if link and not link.startswith("http"):
            link = "https://weixin.sogou.com" + link

        # 公众号名称
        account_el = li.select_one(".all-time-y2") or li.select_one(".s-p a")
        account = account_el.get_text(strip=True) if account_el else ""

        # 摘要
        desc_el = li.select_one(".txt-info")
        desc = desc_el.get_text(strip=True) if desc_el else ""

        # 时间戳（在 script 标签中）
        pub_time = ""
        script_el = li.select_one("script")
        if script_el and script_el.string:
            m = re.search(r"timeConvert\('(\d+)'\)", script_el.string)
            if m:
                ts = int(m.group(1))
                pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

        articles.append({
            "title": title,
            "account": account,
            "desc": desc,
            "url": link,
            "pub_time": pub_time,
        })

    return articles


def search_category(category_name, query, page=1):
    """搜索一个分类关键词"""
    url = (
        f"https://weixin.sogou.com/weixin"
        f"?type=2&query={query}&ie=utf8&s_from=input&_sug_=n&_sug_type_="
        f"&page={page}"
    )
    resp = fetch(url)
    if not resp:
        return []

    # 检测反爬
    if "antispider" in resp.text or "验证码" in resp.text:
        print(f"  [反爬] 搜狗要求验证码，跳过")
        return []

    resp.encoding = "utf-8"
    return parse_sogou_articles(resp.text)


def is_small_account(account_name):
    """判断是否为小号（不在大号黑名单中）"""
    if not account_name:
        return True  # 未知号默认保留
    for big in BIG_ACCOUNTS:
        if big in account_name or account_name in big:
            return False
    return True


def filter_yesterday(articles):
    """保留昨天的文章"""
    yesterday_str = YESTERDAY.strftime("%Y-%m-%d")
    filtered = []
    for a in articles:
        pt = a.get("pub_time", "")
        if pt and len(pt) >= 10:
            if pt[:10] == yesterday_str:
                filtered.append(a)
        else:
            filtered.append(a)  # 无日期的保留
    return filtered


def classify_article(article, category_keywords):
    """用关键词匹配确认文章是否属于该分类"""
    text = article["title"] + " " + article.get("desc", "")
    matched = [kw for kw in category_keywords if kw in text]
    return len(matched) > 0


def deduplicate(articles):
    """按标题去重"""
    seen = set()
    result = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            result.append(a)
    return result


# ============ 主流程 ============

def main():
    # 也可以从 day-1 热点 JSON 中动态提取搜索词
    hot_json_path = os.path.join(OUTPUT_DIR, f"{YESTERDAY_STR}热点新闻.json")
    extra_queries = {}
    if os.path.exists(hot_json_path):
        print(f"发现 {YESTERDAY_STR}热点新闻.json，将提取热门话题关键词补充搜索...")
        with open(hot_json_path, "r", encoding="utf-8") as f:
            hot_data = json.load(f)
        for group in hot_data[:15]:  # 取前15个话题
            cat = group.get("category", "其他")
            # 从话题新闻标题中提取关键词作为补充搜索
            for news in group.get("news", [])[:2]:
                title = news.get("title", "")
                if len(title) >= 4:
                    # 取标题中有意义的部分作为搜索词
                    query = title[:20]  # 截取前20字
                    if cat not in extra_queries:
                        extra_queries[cat] = []
                    extra_queries[cat].append(query)

    print("=" * 55)
    print(f"  公众号少粉爆文爬虫 - {YESTERDAY_STR}热点")
    print("=" * 55)
    print()

    all_results = {}  # {category: [articles]}
    total_searched = 0
    total_found = 0

    categories_list = list(CATEGORIES.items())
    for idx, (cat_name, cat_info) in enumerate(categories_list, 1):
        print(f"[{idx}/{len(categories_list)}] 搜索分类: {cat_name}")

        cat_articles = []

        # 1. 用预定义搜索词
        queries = cat_info["search_queries"]

        # 2. 补充 day-1 热点中的关键词
        for mapped_cat, extra_qs in extra_queries.items():
            if mapped_cat == cat_name or cat_name in mapped_cat:
                queries = queries + extra_qs[:2]
                break

        for query in queries:
            total_searched += 1
            articles = search_category(cat_name, query)
            if articles:
                # 用关键词过滤确认相关性
                for a in articles:
                    a["category"] = cat_name
                cat_articles.extend(articles)

            # 控制请求频率，避免触发反爬
            time.sleep(1.5)

        # 去重
        cat_articles = deduplicate(cat_articles)

        # 过滤日期
        cat_articles = filter_yesterday(cat_articles)

        # 过滤大号，保留少粉号
        small_articles = [a for a in cat_articles if is_small_account(a["account"])]
        big_count = len(cat_articles) - len(small_articles)

        total_found += len(small_articles)
        print(f"  找到 {len(cat_articles)} 篇，过滤大号 {big_count} 篇，"
              f"保留少粉文章 {len(small_articles)} 篇")

        if small_articles:
            all_results[cat_name] = small_articles

    # ============ 输出 ============
    print(f"\n共搜索 {total_searched} 次，找到少粉文章 {total_found} 篇")

    if not all_results:
        print("未找到任何文章，请检查网络或稍后重试。")
        return

    # 格式化文本报告
    lines = []
    lines.append("=" * 70)
    lines.append(f"  {YESTERDAY_STR} 公众号少粉爆文报告")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  共 {len(all_results)} 个分类，{total_found} 篇文章")
    lines.append("=" * 70)

    json_data = []

    for cat_name, articles in all_results.items():
        lines.append("")
        lines.append(f"{'─' * 70}")
        lines.append(f"  【{cat_name}】 {len(articles)} 篇")
        lines.append(f"{'─' * 70}")

        cat_json = {
            "category": cat_name,
            "count": len(articles),
            "articles": [],
        }

        for i, a in enumerate(articles, 1):
            account_tag = f"@{a['account']}" if a["account"] else "@未知号"
            lines.append(f"  {i}. {a['title']}")
            lines.append(f"     {account_tag}")
            if a.get("pub_time"):
                lines.append(f"     时间: {a['pub_time']}")
            if a.get("desc"):
                desc = a["desc"][:100] + ("..." if len(a["desc"]) > 100 else "")
                lines.append(f"     {desc}")
            if a.get("url"):
                lines.append(f"     链接: {a['url']}")

            cat_json["articles"].append({
                "title": a["title"],
                "account": a["account"],
                "desc": a.get("desc", ""),
                "url": a.get("url", ""),
                "pub_time": a.get("pub_time", ""),
                "category": cat_name,
            })

        json_data.append(cat_json)

    lines.append("")
    lines.append("=" * 70)
    lines.append("  报告完毕")
    lines.append("=" * 70)

    report = "\n".join(lines)
    print(report)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n结果已保存到: {OUTPUT_FILE}")

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已保存到: {JSON_FILE}")


if __name__ == "__main__":
    main()
