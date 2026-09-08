// 数值/货币格式化，移植自 game-core.js fmtMoney。
export function fmtMoney(c: unknown): string {
  const n = c == null ? null : parseInt(String(c), 10)
  if (n == null || isNaN(n)) return '—'
  if (n >= 1000) {
    const l = Math.floor(n / 1000)
    const q = n % 1000
    return q ? l + '两' + q + '钱' : l + '两'
  }
  return n + '钱'
}

export function effText(e: unknown): string {
  if (e == null) return ''
  return typeof e === 'string' ? e : JSON.stringify(e)
}
