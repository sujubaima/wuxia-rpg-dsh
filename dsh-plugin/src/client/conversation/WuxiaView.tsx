import { jsx } from 'react/jsx-runtime'

export function WuxiaView() {
  return jsx('div', {
    style: { padding: 24, color: 'var(--dsw-alias-label-secondary, #9a8c6e)' },
    children: '武侠RPG · UI 待重做',
  })
}
