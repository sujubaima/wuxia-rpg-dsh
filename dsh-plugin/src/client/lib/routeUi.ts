// 路由分发器薄封装：组件可像原版 routeUi(d, ctx) 那样调用，真实实现在 store.routeUi。
import { useGameStore } from '../store'
import type { EngineResult } from '../types'

export function routeUi(d: EngineResult, ctx?: { from?: string; showExpl?: boolean }): boolean {
  return useGameStore.getState().routeUi(d, ctx)
}
