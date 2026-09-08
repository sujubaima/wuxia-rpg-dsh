"""雷印 - 叠层概率触发：每次施加时按当前雷印总数掷骰，每层 20% 概率，
命中则触发特殊效果并清除携带者身上所有雷印。

可叠加中性状态，设计为长效（duration<0，由施加方传 -1）：不随回合 tick 消退，
仅靠本触发清除或被净化类移除。叠层越高触发概率越大（5 层即 100% 必触发）。

on_apply(char, entry) 在每次新增雷印条目时触发（可叠加的每次追加都触发），
此时本次条目已入列表，故统计的层数含本次。on_apply 仅传携带者自身，触发效果
暂留空（_trigger_effect）；若将来触发需波及战场其他角色，需改用携带者可触达的
事件返回或扩展钩子签名，当前签名只够作用于携带者自身。
"""
import random

CHANCE_PER_STACK = 0.20  # 每层雷印 20% 触发概率（5 层即 100%）


def on_apply(char, entry):
    """施加时：按当前雷印总数（含本次）掷骰，命中则触发效果并清除所有雷印。

    一次出招施多层时，施加方可置 char['_雷印延迟判定']=True 让本次（及之前）
    的施加跳过判定、仅入列累计层数；最后一层施加前清掉该标志，使最终按累计
    层数掷一次骰——避免中间层提前引爆、夺去多层叠加的更高触发率。
    """
    if char.get("_雷印延迟判定"):
        return  # 批量中间层：雷印已入列累计，不判定，留待最后一层统一结算
    stacks = sum(1 for e in char.get("状态效果", []) if e.get("id") == "leiyin")
    chance = min(1.0, stacks * CHANCE_PER_STACK)
    if random.random() >= chance:
        return  # 未命中，雷印留存继续叠层

    # 命中：触发特殊效果（置追击信号，由施加雷印的武学特效 on_target_resolved 复用本次伤害数值追击）
    _trigger_effect(char, stacks)

    # 移除携带者身上所有雷印（含本次）；走统一入口以触发 on_removed 收尾钩子
    from common import status_manager as sm
    for e in [x for x in char.get("状态效果", []) if x.get("id") == "leiyin"]:
        sm.remove_status(char, e)


def _trigger_effect(char, stacks):
    """雷印触发的特殊效果：置追击信号，由施加雷印的武学特效 on_target_resolved 读取后复用本次
    伤害数值请求追击（额外再落一次等量伤害）。stacks 为触发时的雷印层数。"""
    char["_雷印追击"] = True
