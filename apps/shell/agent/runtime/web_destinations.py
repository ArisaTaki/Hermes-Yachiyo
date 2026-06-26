"""Shared known web destination hints for agent entrypoints."""

from __future__ import annotations

import re


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
