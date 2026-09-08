import { useEffect, useState } from 'react'

const ATTRS = [
  { k: '内功', desc: '派生攻击力与内力上限' },
  { k: '力道', desc: '派生攻击力与气血上限' },
  { k: '身法', desc: '派生速度与防御力' },
  { k: '根骨', desc: '派生识破与气血上限' },
]
const ARTS = [
  { k: '搏击', desc: '搏击技能攻防' }, { k: '剑法', desc: '剑法技能攻防' },
  { k: '刀法', desc: '刀法技能攻防' }, { k: '长兵', desc: '长兵技能攻防' },
  { k: '奇门', desc: '奇门技能攻防' }, { k: '暗器', desc: '暗器技能攻防' },
]
const TECHS = [
  { k: '音律', desc: '抚琴品艺、以乐动情' }, { k: '弈棋', desc: '手谈破局、推演解谜' },
  { k: '诗书', desc: '题诗和答、作文辨伪' }, { k: '绘画', desc: '鉴画识真、绘制图章' },
  { k: '医术', desc: '诊脉辨毒、疗伤验尸' }, { k: '博物', desc: '感知秘密、采集挖掘' },
]
const POLARS = [
  { k: '内功', name: '阴阳', opts: ['阴', '阳', '中'], desc: '阴：内力上限↑、攻击力↓；阳：攻击力↑、内力上限↓' },
  { k: '力道', name: '刚柔', opts: ['刚', '柔', '中'], desc: '刚：暴击↑、精准↓；柔：精准↑、暴击↓' },
  { k: '身法', name: '动静', opts: ['动', '静', '中'], desc: '动：速度↑、防御力↓；静：防御力↑、速度↓' },
  { k: '根骨', name: '巧拙', opts: ['巧', '拙', '中'], desc: '巧：识破↑、气血上限↓；拙：气血上限↑、识破↓' },
]
const START_SKILLS = [
  { type: '搏击', name: '百缠手', school: '丐帮基础拳法', weapon: '拳套', desc: '绵密缠打。' },
  { type: '剑法', name: '太乙玄门剑', school: '武当派基础剑法', weapon: '长剑', desc: '圆融守中。' },
  { type: '刀法', name: '开阖刀法', school: '锦衣卫基础刀法', weapon: '朴刀', desc: '攻守兼备。' },
  { type: '长兵', name: '夜叉棍法', school: '少林寺基础棍法', weapon: '长棍', desc: '横扫直进。' },
  { type: '暗器', name: '蜻蜓点水势', school: '乌衣门基础暗器手法', weapon: '飞刀', desc: '点到即走。' },
  { type: '奇门', name: '分水刺', school: '峨眉派基础奇门兵法', weapon: '峨眉刺', desc: '近身分进。' },
]

const POOLS = { attrs: 24, arts: 36, techs: 36 } as const
const CAP = 12
const GOLD = '#c8a456'
const DIM = '#9a8c6e'
const TEXT = '#e8dcc4'
const BORDER = '#3a2f22'

type Group = keyof typeof POOLS

interface WizardState {
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

export interface CharacterDraft {
  名称: string
  性别: string
  年龄: number
  阵营: string
  一级属性: Record<string, number>
  极性: Record<string, string>
  武艺: Record<string, number>
  技艺: Record<string, number>
  武学: { 名称: string; 等级: number }[]
  携带技能: string[]
  携带物品: string[]
  运转心法: null
  装备: Record<string, string | null>
  物品: unknown[]
}

interface Props {
  existingNames: readonly string[]
  onClose: () => void
  onSubmit: (character: CharacterDraft) => void
}

function freshWizard(): WizardState {
  return {
    step: 1,
    name: '',
    gender: '男',
    age: 18,
    attrs: { 内功: 6, 力道: 6, 身法: 6, 根骨: 6 },
    arts: { 搏击: 6, 剑法: 6, 刀法: 6, 长兵: 6, 奇门: 6, 暗器: 6 },
    techs: { 音律: 6, 弈棋: 6, 诗书: 6, 绘画: 6, 医术: 6, 博物: 6 },
    polar: { 内功: '中', 力道: '中', 身法: '中', 根骨: '中' },
    skill: null,
  }
}

function poolLeft(wizard: WizardState, group: Group): number {
  return POOLS[group] - Object.values(wizard[group]).reduce((sum, value) => sum + value, 0)
}

function randomValues(keys: readonly string[], total: number): Record<string, number> {
  const values = Object.fromEntries(keys.map(key => [key, 0])) as Record<string, number>
  let left = total
  while (left > 0) {
    const key = keys[Math.floor(Math.random() * keys.length)]
    if (values[key] < CAP) {
      values[key] += 1
      left -= 1
    }
  }
  return values
}

const buttonStyle = {
  padding: '7px 16px',
  borderRadius: 6,
  border: `1px solid ${BORDER}`,
  background: 'transparent',
  color: TEXT,
  cursor: 'pointer',
  fontSize: 13,
}

const primaryButtonStyle = {
  ...buttonStyle,
  color: GOLD,
  border: '1px solid #8a6a2a',
}

const inputStyle = {
  width: '100%',
  boxSizing: 'border-box' as const,
  padding: '8px 10px',
  color: TEXT,
  background: '#15110e',
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  outline: 'none',
  fontSize: 12.5,
}

export function CreateWizardPanel({ existingNames, onClose, onSubmit }: Props) {
  const [wizard, setWizard] = useState<WizardState>(freshWizard)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const patch = (value: Partial<WizardState>) => {
    setError('')
    setWizard(current => ({ ...current, ...value }))
  }

  const changePoint = (group: Group, key: string, delta: number) => {
    setError('')
    setWizard(current => {
      const value = current[group][key]
      if (delta < 0 && value <= 0) return current
      if (delta > 0 && (value >= CAP || poolLeft(current, group) <= 0)) return current
      return { ...current, [group]: { ...current[group], [key]: value + delta } }
    })
  }

  const randomAll = () => {
    setError('')
    setWizard(current => ({
      ...current,
      attrs: randomValues(ATTRS.map(item => item.k), POOLS.attrs),
      arts: randomValues(ARTS.map(item => item.k), POOLS.arts),
      techs: randomValues(TECHS.map(item => item.k), POOLS.techs),
      polar: Object.fromEntries(POLARS.map(item => [item.k, item.opts[Math.floor(Math.random() * item.opts.length)]])),
    }))
  }

  const next = () => {
    if (wizard.step === 1) {
      const name = wizard.name.trim()
      if (!name || name.length > 12) {
        setError('姓名须为 1～12 个字。')
        return
      }
      if (wizard.age < 16 || wizard.age > 80) {
        setError('年龄须在 16～80 岁之间。')
        return
      }
      if (existingNames.some(item => item.trim() === name)) {
        setError(`「${name}」已有角色档，请另起一名。`)
        return
      }
      setWizard(current => ({ ...current, name, step: 2 }))
      setError('')
      return
    }

    if (wizard.step === 2) {
      const unfinished = (Object.keys(POOLS) as Group[]).find(group => poolLeft(wizard, group) !== 0)
      if (unfinished) {
        setError('三个点数池均须恰好分完。')
        return
      }
      setWizard(current => ({ ...current, step: 3 }))
      setError('')
      return
    }

    if (!wizard.skill) {
      setError('请选择一门入门武学。')
      return
    }
    const selected = START_SKILLS.find(item => item.type === wizard.skill)
    if (!selected) return

    onSubmit({
      名称: wizard.name,
      性别: wizard.gender,
      年龄: wizard.age,
      阵营: '我方',
      一级属性: { ...wizard.attrs },
      极性: { ...wizard.polar },
      武艺: { ...wizard.arts },
      技艺: { ...wizard.techs },
      武学: [{ 名称: selected.name, 等级: 1 }],
      携带技能: [selected.name],
      携带物品: [],
      运转心法: null,
      装备: { 武器1: selected.weapon, 武器2: null, 护甲: null, 饰品: null, 冠巾: null },
      物品: [],
    })
  }

  const allocation = (group: Group, title: string, definitions: readonly { k: string; desc: string }[]) => (
    <section style={{ marginTop: 14 }}>
      <div style={{ color: TEXT, marginBottom: 7 }}>
        <b>{title}</b>
        <span style={{ color: DIM }}>　剩余 </span>
        <b style={{ color: poolLeft(wizard, group) === 0 ? '#7a9a5a' : GOLD }}>{poolLeft(wizard, group)}</b>
        <span style={{ color: DIM }}> 点　单项 ≤ {CAP}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 7 }}>
        {definitions.map(item => (
          <div key={item.k} title={item.desc} style={{ display: 'grid', gridTemplateColumns: '1fr 28px 32px 28px', alignItems: 'center', gap: 4, padding: '7px 8px', background: '#1a1612', border: `1px solid ${BORDER}`, borderRadius: 6 }}>
            <span style={{ color: TEXT }}>{item.k}</span>
            <button type="button" style={{ ...buttonStyle, padding: 0, height: 26 }} onClick={() => changePoint(group, item.k, -1)}>−</button>
            <b style={{ textAlign: 'center', color: GOLD }}>{wizard[group][item.k]}</b>
            <button type="button" style={{ ...buttonStyle, padding: 0, height: 26 }} onClick={() => changePoint(group, item.k, 1)}>＋</button>
          </div>
        ))}
      </div>
    </section>
  )

  return (
    <div role="region" aria-label="创建角色" style={{ width: '100%', maxHeight: '72vh', overflowY: 'auto', boxSizing: 'border-box', padding: '18px 20px', textAlign: 'left', color: TEXT, fontSize: 13, lineHeight: 1.6, background: '#1a1612', border: '1px solid #6b5224', borderRadius: 10, boxShadow: 'inset 0 0 24px rgba(0,0,0,0.22)', fontFamily: 'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif' }}>
        <h2 style={{ margin: 0, textAlign: 'center', color: GOLD, letterSpacing: 5, fontSize: 22 }}>人物创建</h2>
        <div style={{ margin: '7px 0 18px', textAlign: 'center', color: DIM, fontSize: 13 }}>
          {wizard.step === 1 ? '—— 第一步 · 立名 ——' : wizard.step === 2 ? '—— 第二步 · 分配资质 ——' : '—— 第三步 · 选择初始武学 ——'}
        </div>

        {wizard.step === 1 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
            <label style={{ color: DIM, fontSize: 13 }}>姓名
              <input autoFocus maxLength={12} placeholder="如 沈听雪" value={wizard.name} onChange={event => patch({ name: event.target.value })} style={{ ...inputStyle, marginTop: 5 }} />
            </label>
            <label style={{ color: DIM, fontSize: 13 }}>性别
              <select value={wizard.gender} onChange={event => patch({ gender: event.target.value })} style={{ ...inputStyle, marginTop: 5 }}>
                <option value="男">男</option><option value="女">女</option>
              </select>
            </label>
            <label style={{ color: DIM, fontSize: 13 }}>年龄（16～80）
              <input type="number" min={16} max={80} value={wizard.age} onChange={event => patch({ age: Number.parseInt(event.target.value, 10) || 16 })} style={{ ...inputStyle, marginTop: 5 }} />
            </label>
            <div style={{ gridColumn: '1 / -1', color: DIM, fontSize: 12 }}>姓名不得与现有角色档重名；人设与江湖开场将由 GM 根据档案生成。</div>
          </div>
        )}

        {wizard.step === 2 && (
          <>
            <button type="button" style={primaryButtonStyle} onClick={randomAll}>🎲 随机分配</button>
            {allocation('attrs', '基础属性', ATTRS)}
            {allocation('arts', '武艺', ARTS)}
            {allocation('techs', '技艺', TECHS)}
            <section style={{ marginTop: 15 }}>
              <b>极性</b>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 7, marginTop: 7 }}>
                {POLARS.map(item => (
                  <label key={item.k} title={item.desc} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 8px', color: DIM, background: '#1a1612', border: `1px solid ${BORDER}`, borderRadius: 6 }}>
                    <span style={{ flex: 1 }}>{item.name}</span>
                    <select value={wizard.polar[item.k]} onChange={event => setWizard(current => ({ ...current, polar: { ...current.polar, [item.k]: event.target.value } }))} style={{ ...inputStyle, width: 64, padding: '4px 6px' }}>
                      {item.opts.map(option => <option key={option} value={option}>{option}</option>)}
                    </select>
                  </label>
                ))}
              </div>
              <div style={{ marginTop: 6, color: DIM, fontSize: 12 }}>中为无修正；悬停各项可查看派生方向。</div>
            </section>
          </>
        )}

        {wizard.step === 3 && (
          <>
            <div style={{ marginBottom: 10, color: DIM, fontSize: 12 }}>择一门入门武学，并配发对应兵器。</div>
            <div style={{ display: 'grid', gap: 8 }}>
              {START_SKILLS.map(item => {
                const selected = wizard.skill === item.type
                return (
                  <button key={item.type} type="button" onClick={() => patch({ skill: item.type })} style={{ padding: '10px 12px', textAlign: 'left', cursor: 'pointer', color: selected ? GOLD : TEXT, background: selected ? 'rgba(200,164,86,0.12)' : '#1a1612', border: `1px solid ${selected ? '#8a6a2a' : BORDER}`, borderRadius: 7 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600 }}>《{item.name}》</div>
                    <div style={{ marginTop: 3, color: DIM, fontSize: 11 }}>{item.school} ｜ 配发【{item.weapon}】 ｜ {item.desc}</div>
                  </button>
                )
              })}
            </div>
          </>
        )}

        <div style={{ minHeight: 22, paddingTop: 10, color: '#c45a4a', fontSize: 13 }}>{error}</div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingTop: 8, borderTop: `1px solid ${BORDER}` }}>
          <button type="button" style={buttonStyle} onClick={onClose}>返回标题</button>
          <div style={{ display: 'flex', gap: 8 }}>
            {wizard.step > 1 && <button type="button" style={buttonStyle} onClick={() => patch({ step: wizard.step - 1 })}>上一步</button>}
            <button type="button" style={primaryButtonStyle} onClick={next}>{wizard.step === 3 ? '完成建号' : '下一步'}</button>
          </div>
        </div>
    </div>
  )
}
