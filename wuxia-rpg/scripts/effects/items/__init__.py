"""物品特效脚本接口。

物品JSON可选「物品特效」字段引用本目录脚本，统一签名为 `on_xxx(source, ctx)`。
物品可进入 on_action、on_target_confirmed、on_settle、on_before_commit、
on_target_resolved；不新增闪避和识破。现有纯数据「使用效果」保持不变。
"""
