"""梅花易数 - 精准+40%（梅花心易运转时长效；心法第10境起为+60%）"""


def _xinfa_level(char):
    name = char.get("运转心法")
    if not name:
        return 0
    for s in char.get("武学", []):
        if isinstance(s, dict) and s.get("名称") == name:
            return s.get("等级", 1)
    return 0


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "精准":
        ratio = 1.6 if _xinfa_level(char) >= 10 else 1.4
        return round(base_value * ratio)
    return base_value
