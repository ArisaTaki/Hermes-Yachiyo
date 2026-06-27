"""Shared known web destination hints for agent entrypoints."""

from __future__ import annotations

import re
from urllib.parse import quote_plus


KNOWN_WEB_DESTINATION_URLS: dict[str, str] = {
    "baidu": "https://www.baidu.com",
    "bilibili": "https://www.bilibili.com",
    "b站": "https://www.bilibili.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "douban": "https://www.douban.com",
    "douyin": "https://www.douyin.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "google": "https://www.google.com",
    "googledocs": "https://docs.google.com",
    "googledrive": "https://drive.google.com",
    "jd": "https://www.jd.com",
    "jingdong": "https://www.jd.com",
    "perplexity": "https://www.perplexity.ai",
    "reddit": "https://www.reddit.com",
    "rednote": "https://www.xiaohongshu.com",
    "taobao": "https://www.taobao.com",
    "tieba": "https://tieba.baidu.com",
    "tiktok": "https://www.tiktok.com",
    "twitter": "https://x.com",
    "weibo": "https://weibo.com",
    "x": "https://x.com",
    "xiaohongshu": "https://www.xiaohongshu.com",
    "yt": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "youtubemusic": "https://music.youtube.com",
    "zhihu": "https://www.zhihu.com",
    "百度": "https://www.baidu.com",
    "百度贴吧": "https://tieba.baidu.com",
    "抖音": "https://www.douyin.com",
    "豆瓣": "https://www.douban.com",
    "哔哩哔哩": "https://www.bilibili.com",
    "京东": "https://www.jd.com",
    "贴吧": "https://tieba.baidu.com",
    "淘宝": "https://www.taobao.com",
    "推特": "https://x.com",
    "微博": "https://weibo.com",
    "小红书": "https://www.xiaohongshu.com",
    "知乎": "https://www.zhihu.com",
    "谷歌": "https://www.google.com",
}

BROWSER_ONLY_WEB_DESTINATION_URLS: dict[str, str] = {
    "applemusic": "https://music.apple.com",
    "music": "https://music.apple.com",
    "音乐": "https://music.apple.com",
}

KNOWN_WEB_DESTINATION_SEARCH_URLS: dict[str, str] = {
    "baidu": "https://www.baidu.com/s?wd={query}",
    "bilibili": "https://search.bilibili.com/all?keyword={query}",
    "b站": "https://search.bilibili.com/all?keyword={query}",
    "douban": "https://www.douban.com/search?q={query}",
    "github": "https://github.com/search?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "jd": "https://search.jd.com/Search?keyword={query}",
    "jingdong": "https://search.jd.com/Search?keyword={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "rednote": "https://www.xiaohongshu.com/search_result?keyword={query}",
    "taobao": "https://s.taobao.com/search?q={query}",
    "twitter": "https://x.com/search?q={query}",
    "weibo": "https://s.weibo.com/weibo?q={query}",
    "x": "https://x.com/search?q={query}",
    "xiaohongshu": "https://www.xiaohongshu.com/search_result?keyword={query}",
    "yt": "https://www.youtube.com/results?search_query={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "zhihu": "https://www.zhihu.com/search?type=content&q={query}",
    "知乎": "https://www.zhihu.com/search?type=content&q={query}",
    "百度": "https://www.baidu.com/s?wd={query}",
    "豆瓣": "https://www.douban.com/search?q={query}",
    "哔哩哔哩": "https://search.bilibili.com/all?keyword={query}",
    "京东": "https://search.jd.com/Search?keyword={query}",
    "淘宝": "https://s.taobao.com/search?q={query}",
    "推特": "https://x.com/search?q={query}",
    "微博": "https://s.weibo.com/weibo?q={query}",
    "小红书": "https://www.xiaohongshu.com/search_result?keyword={query}",
    "谷歌": "https://www.google.com/search?q={query}",
}


def known_web_destination_url_hint(text: str) -> str:
    value = str(text or "").strip()
    patterns = (
        r"(?:打开|启动|运行|拉起|开启|用|在)\s*"
        r"(?:浏览器|chrome|google\s*chrome|google|谷歌|百度|safari)"
        r"(?:里|中|上|内)?\s*(?:并|然后|再|接着|之后)?\s*"
        r"(?:打开|访问|浏览|前往|去|上)\s*(?P<site>[^。！？!?，,]+)",
        r"(?:打开|访问|浏览|前往|去|上)\s*(?P<site>[^。！？!?，,]+)",
        r"(?P<site>[^。！？!?，,]+?)\s*(?:官网|官方网站|官方站|网页|网站|站点|首页|主页)$",
        r"\b(?:open|launch|start|use)\s+(?:the\s+)?"
        r"(?:browser|chrome|google\s+chrome|google|safari)\s+"
        r"(?:and\s+|then\s+)?(?:open|visit|browse|go\s+to)\s+(?P<site>[^.!?,]+)",
        r"\b(?:open|visit|browse|go\s+to)\s+(?P<site>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        url = known_web_destination_url(match.group("site"))
        if url:
            return url
    return ""


def known_web_destination_url(site_name: str) -> str:
    site = re.sub(
        r"\s*(?:官网|官方网站|官方站|网页|网站|站点|首页|主页|首页面|site|website|homepage|home\s+page)$",
        "",
        str(site_name or "").strip(),
        flags=re.IGNORECASE,
    )
    site = re.sub(r"^(?:一下|下|这个|那个)\s*", "", site).strip()
    compact = re.sub(r"[\s._·-]+", "", site.lower())
    return KNOWN_WEB_DESTINATION_URLS.get(compact, "")


def known_web_destination_search_url(site_name: str, query: str) -> str:
    site = re.sub(
        r"\s*(?:官网|官方网站|官方站|网页|网站|站点|首页|主页|首页面|site|website|homepage|home\s+page)$",
        "",
        str(site_name or "").strip(),
        flags=re.IGNORECASE,
    )
    site = re.sub(r"^(?:一下|下|这个|那个)\s*", "", site).strip()
    compact = re.sub(r"[\s._·-]+", "", site.lower())
    template = KNOWN_WEB_DESTINATION_SEARCH_URLS.get(compact, "")
    clean_query = str(query or "").strip()
    if not template or not clean_query:
        return ""
    return template.format(query=quote_plus(clean_query))


def browser_only_web_destination_url(site_name: str) -> str:
    site = re.sub(
        r"\s*(?:官网|官方网站|官方站|网页|网站|站点|site|website)$",
        "",
        str(site_name or "").strip(),
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"[\s._-]+", "", site.lower())
    return BROWSER_ONLY_WEB_DESTINATION_URLS.get(compact, "")
