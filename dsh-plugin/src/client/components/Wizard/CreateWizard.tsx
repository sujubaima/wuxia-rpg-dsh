import { useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore } from '../../store'
import { Btn } from '../ui'

const ATTRS = [
  { k: '内功', desc: '派生攻击力与内力上限' },
  { k: '力道', desc: '派生攻击力与气血上限' },
  { k: '身法', desc: '派生速度与防御力' },
  { k: '根骨', desc: '派生识破与气血上限' },
]
const ARTS = [
  { k: '搏击', desc: '搏击技能攻防' }, { k: '剑法', desc: '剑法技能攻防' }, { k: '刀法', desc: '刀法技能攻防' },
  { k: '长兵', desc: '长兵技能攻防' }, { k: '奇门', desc: '奇门技能攻防' }, { k: '暗器', desc: '暗器技能攻防' },
]
const TECHS = [
  { k: '音律', desc: '抚琴品艺、以乐动情' }, { k: '弈棋', desc: '手谈破局、推演解谜' },
  { k: '诗书', desc: '题诗和答、作文辨伪' }, { k: '绘画', desc: '鉴画识真、绘制图章' },
  { k: '医术', desc: '诊脉辨毒、疗伤验尸' }, { k: '博物', desc: '感知秘密、采集挖掘' },
]
const POLARS = [
  { k: '内功', name: '阴阳', opts: ['阴', '阳', '中'], desc: '阴:内力上限↑攻击力↓ / 阳:攻击力↑内力上限↓ / 中:无修正' },
  { k: '力道', name: '刚柔', opts: ['刚', '柔', '中'], desc: '刚:暴击↑精准↓ / 柔:精准↑暴击↓ / 中:无修正' },
  { k: '身法', name: '动静', opts: ['动', '静', '中'], desc: '动:速度↑防御力↓ / 静:防御力↑速度↓ / 中:无修正' },
  { k: '根骨', name: '巧拙', opts: ['巧', '拙', '中'], desc: '巧:识破↑气血上限↓ / 拙:气血上限↑识破↓ / 中:无修正' },
]
const START_SKILLS = [
  { type: '搏击', name: '百缠手', school: '丐帮基础拳法', weapon: '拳套', desc: '丐帮入门拳掌，绵密缠打。' },
  { type: '剑法', name: '太乙玄门剑', school: '武当派基础剑法', weapon: '长剑', desc: '武当太极入门剑，圆融守中。' },
  { type: '刀法', name: '开阖刀法', school: '锦衣卫基础刀法', weapon: '朴刀', desc: '北镇抚司开合刀式，攻守兼备。' },
  { type: '长兵', name: '夜叉棍法', school: '少林寺基础棍法', weapon: '长棍', desc: '少林入门长棍，横扫直进。' },
  { type: '暗器', name: '蜻蜓点水势', school: '乌衣门基础暗器手法', weapon: '飞刀', desc: '乌衣门轻灵暗器手法，点到即走。' },
  { type: '奇门', name: '分水刺', school: '峨眉派基础奇门兵法', weapon: '峨眉刺', desc: '峨眉奇门短兵，近身分进。' },
]
const POOLS: Record<'attrs' | 'arts' | 'techs', number> = { attrs: 24, arts: 36, techs: 36 }
const PCAP = 12

interface Wiz {
  step: number
  name: string
  gender: string
  age: number
  attrs: Record<string, number>
  arts: Record<string, number>
  techs: Record<string, number>
  polar: Record<string, string>
  skill: string | null
}

function freshWiz(): Wiz {
  return {
    step: 1, name: '', gender: '男', age: 18,
    attrs: { 内功: 6, 力道: 6, 身法: 6, 根骨: 6 },
    arts: { 搏击: 6, 剑法: 6, 刀法: 6, 长兵: 6, 奇门: 6, 暗器: 6 },
    techs: { 音律: 6, 弈棋: 6, 诗书: 6, 绘画: 6, 医术: 6, 博物: 6 },
    polar: { 内功: '中', 力道: '中', 身法: '中', 根骨: '中' },
    skill: null,
  }
}

function poolLeft(w: Wiz, group: keyof typeof POOLS) {
  const total = Object.values(w[group]).reduce((a, b) => a + b, 0)
  return POOLS[group] - total
}

export function CreateWizard() {
  const open = useGameStore(s => s.wizardOpen)
  const close = useGameStore(s => s.closeWizard)
  const send = useGameStore(s => s.send)
  const enterGame = useGameStore(s => s.enterGame)
  const [wiz, setWiz] = useState<Wiz>(freshWiz)
  const [err, setErr] = useState('')

  useEffect(() => { if (open) { setWiz(freshWiz()); setErr('') } }, [open])
  if (!open) return null

  const patch = (p: Partial<Wiz>) => setWiz(w => ({ ...w, ...p }))

  const randomAlloc = (group: 'attrs' | 'arts' | 'techs', defs: { k: string }[]) => {
    const keys = defs.map(d => d.k)
    setWiz(w => {
      const next = { ...w, [group]: { ...w[group] } }
      for (const k of keys) next[group][k] = 0
      let left = POOLS[group]
      let guard = left * 100 + 200
      while (left > 0 && guard-- > 0) {
        const k = keys[Math.floor(Math.random() * keys.length)]
        if (next[group][k] < PCAP) { next[group][k]++; left-- }
      }
      return next
    })
  }
  const randomPolar = () => setWiz(w => {
    const polar = { ...w.polar }
    for (const d of POLARS) polar[d.k] = d.opts[Math.floor(Math.random() * d.opts.length)]
    return { ...w, polar }
  })

  const next = async () => {
    if (wiz.step === 1) {
      if (!wiz.name) { setErr('请赐姓名。'); return }
      if (!(wiz.age >= 16 && wiz.age <= 80)) { setErr('年龄须年满十六且不逾八旬（16~80）。'); return }
      patch({ step: 2 }); return
    }
    if (wiz.step === 2) {
      for (const g of ['attrs', 'arts', 'techs'] as const) {
        if (poolLeft(wiz, g) !== 0) { setErr('点数尚未分完（各池需恰好用完）。'); return }
      }
      patch({ step: 3 }); return
    }
    // step3 submit
    if (!wiz.skill) { setErr('请择一门入门武学。'); return }
    await submit()
  }

  const submit = async () => {
    const sk = START_SKILLS.find(s => s.type === wiz.skill)!
    setErr('校验姓名…')
    try {
      const all = await fetchUi({ 类型: '开始游戏' })
      const clash = ((all.存档列表 as any[]) || []).find(s => (s.角色名 || '') === wiz.name)
      if (clash) { setErr(`「${wiz.name}」已有人在闯江湖（slot ${clash.slot}），请另起一名。`); return }
    } catch { /* 校验失败不阻塞 */ }
    const char = {
      名称: wiz.name, 性别: wiz.gender, 年龄: wiz.age, 阵营: '我方',
      一级属性: { ...wiz.attrs }, 极性: { ...wiz.polar }, 武艺: { ...wiz.arts }, 技艺: { ...wiz.techs },
      武学: [{ 名称: sk.name, 等级: 1 }], 携带技能: [sk.name], 携带物品: [],
      运转心法: null,
      装备: { 武器1: sk.weapon, 武器2: null, 护甲: null, 饰品: null, 冠巾: null }, 物品: [],
    }
    const directive =
      `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n` +
      `【建号委托】玩家已进入 wuxia-rpg 游戏会话（此消息起，玩家输入原则上都是游戏指令，按游戏规则执行）。\n` +
      `玩家经创建向导选定角色参数（档案尚未落盘，人设留空）。\n` +
      `角色档案：${JSON.stringify(char)}\n` +
      `请按序完成：1) 为该角色撰写「人设」（性格/背景，不得点明具体目的与伏笔、不得有明确门派归属）并入档案；` +
      `2) 携完整档案调用「创建角色」（go 隐藏界面——新档/物资/首档一并落盘）；` +
      `3) 据建号返回的落点与时辰撰写开场白与初始剧情，以下一条 engine.py judge（顶层 \`当前剧情\`/\`场景要素\`/\`经历概括\`）完成首屏渲染（exploration-ui）。`
    close()
    enterGame()
    void send(directive, { hidden: true })
  }

  const allocGrid = (group: 'attrs' | 'arts' | 'techs', defs: { k: string; desc: string }[], tip: string) => (
    <div key={group}>
      <div className="pts">
        <b>{group === 'attrs' ? '基础属性（派生命/攻/速/防/识破）' : group === 'arts' ? '武艺（对应武学攻防）' : '技艺（游历判定）'}</b>
        {'　'}剩余 <span className="pool">{poolLeft(wiz, group)}</span> 点　单项 ≤ {PCAP}
      </div>
      <div className="alloc">
        {defs.map(d => (
          <div className="a-item" key={d.k} title={d.desc}>
            <span className="nm">{d.k}</span>
            <button className="abtn" onClick={() => setWiz(w => w[group][d.k] > 0 ? { ...w, [group]: { ...w[group], [d.k]: w[group][d.k] - 1 } } : w)}>−</button>
            <span className="val">{wiz[group][d.k]}</span>
            <button className="abtn" onClick={() => setWiz(w => w[group][d.k] < PCAP && poolLeft(w, group) > 0 ? { ...w, [group]: { ...w[group], [d.k]: w[group][d.k] + 1 } } : w)}>＋</button>
          </div>
        ))}
      </div>
      <div className="tips">{tip}</div>
    </div>
  )

  return (
    <div id="modCreate" className="show">
      <div className="wiz">
        <h2>人物创建</h2>
        <div className="step">{wiz.step === 1 ? '—— 第一步 · 立名 ——' : wiz.step === 2 ? '—— 第二步 · 分配资质 ——' : '—— 第三步 · 选择初始武学 ——'}</div>
        <div id="wizBody">
          {wiz.step === 1 && (
            <div className="wrow">
              <div className="wfield"><label>姓名</label>
                <input maxLength={12} placeholder="如 沈听雪" value={wiz.name} onChange={e => patch({ name: e.target.value.trim() })} />
              </div>
              <div className="wfield"><label>性别</label>
                <select value={wiz.gender} onChange={e => patch({ gender: e.target.value })}>
                  <option value="男">男</option><option value="女">女</option>
                </select>
              </div>
              <div className="wfield"><label>年龄（16~80）</label>
                <input type="number" min={16} max={80} value={wiz.age} onChange={e => patch({ age: parseInt(e.target.value, 10) || 16 })} />
              </div>
              <div className="tips">姓名 1~12 字，不得与江湖已有角色重名；性别男/女；年龄须满十六且不逾八旬。</div>
            </div>
          )}
          {wiz.step === 2 && (
            <>
              <div className="wrow">
                <Btn primary title="一次性把三池随机分完（单项≤12）并随机四项极性，可再手动微调"
                  onClick={() => { randomAlloc('attrs', ATTRS); randomAlloc('arts', ARTS); randomAlloc('techs', TECHS); randomPolar() }}>🎲 随机分配</Btn>
              </div>
              {allocGrid('attrs', ATTRS, '每项预分配6点，合计24点已满，仅可调整单项分布（单项≤12）。')}
              {allocGrid('arts', ARTS, '合计36点必须分完。')}
              {allocGrid('techs', TECHS, '合计36点必须分完。')}
              <div className="pts"><b>极性</b>　各择其一</div>
              <div className="polar">
                {POLARS.map(d => (
                  <div className="p-item" key={d.k} title={d.desc}>
                    <span className="nm">{d.name}</span>
                    <select value={wiz.polar[d.k]} onChange={e => setWiz(w => ({ ...w, polar: { ...w.polar, [d.k]: e.target.value } }))}>
                      {d.opts.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              <div className="tips">极性微调同一属性的两个派生方向，中=无修正，可随时参考上方描述。</div>
            </>
          )}
          {wiz.step === 3 && (
            <>
              <div className="tips">择一门入门武学并配发对应兵器（习武方向不必与武艺加点一致，但相符更顺）。</div>
              <div className="skillpick">
                {START_SKILLS.map(s => (
                  <div key={s.type} className={'sk' + (wiz.skill === s.type ? ' sel' : '')} onClick={() => patch({ skill: s.type })}>
                    <div className="sn">《{s.name}》</div>
                    <div className="sd">{s.school} ｜ 配发【{s.weapon}】 ｜ {s.desc}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        <div id="createErr">{err}</div>
        <div className="wnav">
          <Btn onClick={close}>返回标题</Btn>
          <div className="right">
            {wiz.step > 1 && <Btn onClick={() => patch({ step: wiz.step - 1 })}>上一步</Btn>}
            <Btn primary onClick={() => void next()}>{wiz.step === 3 ? '完成建号' : '下一步'}</Btn>
          </div>
        </div>
      </div>
    </div>
  )
}
