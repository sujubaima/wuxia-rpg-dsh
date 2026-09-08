"""散功 - 携带者心法失效

无自身行为钩子。通过 status_filter() 工厂声明状态过滤函数：
携带者有散功时，过滤函数令携带者身上 `来源类型=="心法"` 的状态条目不生效——
即心法所生长效状态（on_modify_attr/on_turn_end/on_target_confirmed 等钩子）一律不触发。
状态条目本身保留，散功消失即恢复——天然可逆，无需重施心法。

filter 由 battle_engine.active_status_entries 读取生效状态时现场从本工厂取，
按角色身上状态区分（A 的散功只影响 A），与角色状态同生命周期：状态在 filter 在，
状态移除（tick/清场/净化/任意途径）filter 自然失效。不进内存注册表，跨回合/跨进程
（battle_state.json 序列化）均一致。
"""


def status_filter():
    """返回过滤函数：禁用携带者心法（来源类型=='心法' 的状态不生效）。"""
    return lambda carrying, eff: eff.get("来源类型") != "心法"
