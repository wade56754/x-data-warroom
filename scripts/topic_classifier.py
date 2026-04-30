"""
Topic classifier for Wade's X tweets.
No LLM, no new deps — pure keyword matching with priority rules.

Priority order:
1. 媒体推/转推: text is t.co short link OR label starts with 'RT @'
2. WADE_CATEGORIES dict order (first keyword hit wins)
3. Fallback → 泛流量/其他

v1.1 changes: added 两性/婚恋 and 心理学/科学 categories; expanded keywords
for 知识付费与 IP, 哲学与思考, 认知与社会, AI 与工具.
"""

from __future__ import annotations

WADE_CATEGORIES: dict[str, list[str]] = {
    # 1. 媒体推/转推（特殊规则：t.co 短链 + RT @ 前缀，词典空）
    "媒体推/转推": [],

    # 2. 两性/婚恋（新类目，专一关键词）
    "两性/婚恋": [
        "一夫一妻", "妻妾", "彩礼", "嫁人", "娶妻",
        "出轨", "背叛", "约会", "暗恋",
        "男的好色", "女的贪财", "男人女人", "男女", "两性", "性别",
        "婚恋", "结婚", "婚姻", "感情", "爱情", "恋爱",
        "破防",
    ],

    # 3. 心理学/科学（新类目，学者+实验+理论）
    "心理学/科学": [
        "心理学", "博弈论", "进化心理", "认知偏误", "认知科学",
        "卡尼曼", "塔勒布", "邓巴", "韦伯", "桑德斯", "buss",
        "实验", "受试者", "脑电", "神经", "心流",
        "公羊博弈", "二八定律", "自由意志", "反脆弱",
        "勒内", "哈佛", "加州大学", "1992 年", "1983 年",
    ],

    # 4. AI 与工具（v1 + 补充）
    "AI 与工具": [
        "ai", "claude", "gpt", "codex", "cursor", "mcp", "skill", "agent", "llm",
        "大模型", "openai", "anthropic", "gemini", "supabase", "提示词", "prompt",
        "编程", "代码", "token", "api", "模型", "智能体", "obsidian",
        "deepseek", "豆包", "ollama", "claude code", "翔宇", "openclaw",
    ],

    # 5. 知识付费与 IP（v1 + 补充：流量/变现/平台杂谈）
    "知识付费与 IP": [
        "知识付费", "个人 ip", "个人品牌", "私域", "涨粉", "社群", "付费", "变现",
        "咨询", "副业", "公众号", "账号", "运营", "流量", "博主", "内容创作",
        "自媒体", "粉丝", "小红书", "youtube", "推特", "x 平台",
        "twitter", "黄推", "vpn", "浏览量", "收益", "互动", "万粉",
        "开个号", "做号", "做账号", "ip 变现", "渠道", "受众", "圈子",
    ],

    # 6. 哲学与思考（v1 + 补充：典故/历史人物/自我成长）
    "哲学与思考": [
        "哲学", "庄子", "孟子", "尼采", "罗振宇", "万维钢", "芒格", "认知",
        "思维", "反差", "本质", "原理", "逻辑", "悖论", "第一性",
        "斯多葛", "孔乙己", "长衫", "西游记", "三国", "曹操", "刘备", "孙权",
        "猪八戒", "蒙娜丽莎", "卢浮宫",
        "价值观", "理性", "感性", "智慧", "顿悟", "醍醐灌顶",
        "毁掉一个聪明人",
    ],

    # 7. 认知与社会（v1 + 补充：创业/搞钱/阶级/财富观）
    "认知与社会": [
        "90 后", "00 后", "打工人", "老板", "创业者", "中产", "焦虑", "内卷",
        "躺平", "体制", "北京", "上海", "深圳", "互联网", "大厂", "阶级",
        "中国", "美国", "时代", "代际",
        "搞钱", "赚钱", "有钱人", "穷人", "富人", "屌丝", "底层",
        "创业", "被迫创业", "上班", "失业", "辞职",
        "中医", "西医", "英文", "中文", "西方", "东方", "文化",
        "亲戚", "面子", "刚需", "理财", "风险",
        "白短袖", "工资", "月薪", "年薪", "收入",
    ],

    # 8. 段子与吐槽（v1 不变）
    "段子与吐槽": [
        "马斯克", "建国", "老登", "吐槽", "哈哈", "评论区", "懂王", "笑死",
        "卧槽", "我操", "嘿嘿",
    ],

    # 9. 泛流量/其他（fallback，词典空）
    "泛流量/其他": [],
}

_ORDERED_CATS = list(WADE_CATEGORIES.keys())


def classify(text: str | None, label: str | None) -> str:
    """
    Classify a single tweet into one of Wade's 7 categories.

    Parameters
    ----------
    text  : raw tweet text (may be None)
    label : tweet label / account tag (may be None)

    Returns
    -------
    Category string from WADE_CATEGORIES keys.
    """
    # Normalise to str
    text_str = (text or "").strip()
    label_str = (label or "").strip()

    # --- Rule 1: 媒体推/转推 ---
    # text is purely a t.co short link (media card push / quoted media)
    if text_str.startswith("https://t.co") and len(text_str.split()) == 1:
        return "媒体推/转推"
    # retweet: label starts with 'RT @'
    if label_str.startswith("RT @"):
        return "媒体推/转推"

    # NULL / empty text → fallback
    if not text_str:
        return "泛流量/其他"

    lowered = text_str.lower()

    # --- Rule 2: keyword matching in priority order ---
    for cat, keywords in WADE_CATEGORIES.items():
        if not keywords:
            continue  # skip structural categories (媒体推/转推, 泛流量/其他)
        for kw in keywords:
            if kw.lower() in lowered:
                return cat

    # --- Rule 3: fallback ---
    return "泛流量/其他"


def classify_batch(rows: list[tuple[str, str | None, str | None]]) -> list[tuple[str, str]]:
    """
    Classify a batch of tweets.

    Parameters
    ----------
    rows : list of (tweet_id, text, label)

    Returns
    -------
    list of (tweet_id, topic)
    """
    return [(tweet_id, classify(text, label)) for tweet_id, text, label in rows]


# ---------------------------------------------------------------------------
# Self-tests (≥10 fixtures)
# ---------------------------------------------------------------------------

def _run_self_tests() -> bool:
    fixtures = [
        # (text, label, expected_category, description)
        (
            "https://t.co/Mef7Ujxb5U",
            "自动追踪",
            "媒体推/转推",
            "pure t.co link → 媒体推/转推",
        ),
        (
            "These are amazing AI tools you should try.",
            "RT @someone",
            "媒体推/转推",
            "RT@ label overrides keywords → 媒体推/转推",
        ),
        (
            "Claude 3.5 Sonnet 写代码比任何程序员都快",
            "Wade",
            "AI 与工具",
            "claude keyword → AI 与工具",
        ),
        (
            "用 GPT 做内容创作，自媒体人的效率工具",
            "Wade",
            "AI 与工具",
            "gpt keyword beats 知识付费 keywords (dict order)",
        ),
        (
            "知识付费的本质是贩卖焦虑",
            "Wade",
            "知识付费与 IP",
            "知识付费 keyword → 知识付费与 IP",
        ),
        (
            "打工人的尽头是什么？",
            "Wade",
            "认知与社会",
            "打工人 keyword → 认知与社会",
        ),
        (
            "尼采说：没有痛苦就没有哲学",
            "Wade",
            "哲学与思考",
            "尼采 keyword → 哲学与思考",
        ),
        (
            "老登又开始说教了哈哈哈哈",
            "Wade",
            "段子与吐槽",
            "老登 keyword → 段子与吐槽",
        ),
        (
            None,
            "Wade",
            "泛流量/其他",
            "None text → 泛流量/其他",
        ),
        (
            "",
            "Wade",
            "泛流量/其他",
            "empty text → 泛流量/其他",
        ),
        (
            "MCP server 调试踩坑记录，token 消耗优化",
            "Wade",
            "AI 与工具",
            "mcp + token keywords → AI 与工具",
        ),
        (
            "Prompt engineering 是 2024 年最值钱的技能",
            "Wade",
            "AI 与工具",
            "prompt keyword (case-insensitive) → AI 与工具",
        ),
        (
            "深圳互联网大厂裁员潮，中产焦虑到天花板",
            "Wade",
            "认知与社会",
            "深圳 keyword → 认知与社会",
        ),
        (
            "芒格的第一性原理：从根本上想",
            "Wade",
            "哲学与思考",
            "芒格 keyword → 哲学与思考",
        ),
        # --- 两性/婚恋 新类目（v1.1）---
        (
            "一夫一妻制保护的是谁？",
            "Wade",
            "两性/婚恋",
            "一夫一妻 keyword → 两性/婚恋",
        ),
        (
            "男的好色女的贪财，这是人性还是偏见？",
            "Wade",
            "两性/婚恋",
            "男的好色 keyword → 两性/婚恋",
        ),
        (
            "彩礼到底该不该给？感情的问题没有标准答案",
            "Wade",
            "两性/婚恋",
            "彩礼 keyword → 两性/婚恋 (v1.1 upgrade from fallback)",
        ),
        # --- 心理学/科学 新类目（v1.1）---
        (
            "博弈论里的公羊博弈，解释了为什么人总陷入内耗",
            "Wade",
            "心理学/科学",
            "博弈论 keyword → 心理学/科学",
        ),
        (
            "卡尼曼冰水实验：你的痛苦记忆只记最后 60 秒",
            "Wade",
            "心理学/科学",
            "卡尼曼 keyword → 心理学/科学",
        ),
        (
            "邓巴研究发现日常对话有 65% 都是八卦",
            "Wade",
            "心理学/科学",
            "邓巴 keyword → 心理学/科学",
        ),
        # --- 认知与社会 补充（v1.1）---
        (
            "被迫创业和主动创业完全是两种体验",
            "Wade",
            "认知与社会",
            "被迫创业 keyword → 认知与社会",
        ),
        (
            "搞钱就靠一件白短袖，月薪三万的秘密",
            "Wade",
            "认知与社会",
            "搞钱 + 白短袖 + 月薪 keywords → 认知与社会",
        ),
        (
            "英文比中文先进？这是一种文化殖民",
            "Wade",
            "认知与社会",
            "英文 keyword → 认知与社会",
        ),
        # --- 哲学与思考 补充（v1.1）---
        (
            "斯多葛学派的核心：控制你能控制的",
            "Wade",
            "哲学与思考",
            "斯多葛 keyword → 哲学与思考",
        ),
        (
            "孔乙己脱下长衫的那一刻，才真正活了",
            "Wade",
            "哲学与思考",
            "孔乙己 keyword → 哲学与思考",
        ),
    ]

    passed = 0
    failed = 0
    for text, label, expected, desc in fixtures:
        result = classify(text, label)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            failed += 1
            print(f"  {status}  {desc}")
            print(f"        got={result!r}  expected={expected!r}")
        else:
            passed += 1
            print(f"  {status}  {desc}")

    print(f"\nSelf-test: {passed} passed, {failed} failed out of {len(fixtures)} fixtures")
    return failed == 0


if __name__ == "__main__":
    ok = _run_self_tests()
    raise SystemExit(0 if ok else 1)
