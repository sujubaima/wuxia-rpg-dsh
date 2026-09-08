import { create } from 'zustand'

export interface PartyMember {
  名称: string
  气血: number
  气血上限: number
  内力: number
  内力上限: number
}

export interface PartyStatePayload {
  体力?: number | null
  金钱?: number | null
  队伍状态?: any[]
  槽位?: number
}

interface PartyState {
  体力: number | null
  金钱: number | null
  成员: PartyMember[]
  slot: number | null
  set: (data: PartyStatePayload) => void
  clear: () => void
}

export const useParty = create<PartyState>((set) => ({
  体力: null,
  金钱: null,
  成员: [],
  slot: null,
  set: (data) => set({
    ...(data.体力 != null ? { 体力: data.体力 } : {}),
    ...(data.金钱 != null ? { 金钱: data.金钱 } : {}),
    ...(data.队伍状态 ? { 成员: data.队伍状态 as PartyMember[] } : {}),
    ...(data.槽位 != null ? { slot: data.槽位 } : {}),
  }),
  clear: () => set({ 体力: null, 金钱: null, 成员: [], slot: null }),
}))

export function applyPartyState(data?: PartyStatePayload | null): void {
  if (!data) return
  useParty.getState().set({
    体力: data.体力,
    金钱: data.金钱,
    队伍状态: data.队伍状态,
    槽位: data.槽位,
  })
}
