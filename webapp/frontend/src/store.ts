// UI 상태 (zustand). 서버 데이터는 각 컴포넌트가 필요할 때 가져오고, 여기엔 "무엇을 보고 있는가"만 둔다.

import { create } from 'zustand'
import { api, type DocumentMeta, type Health } from './api'

interface AppState {
  documents: DocumentMeta[]
  selectedId: string | null
  /** 유료 작업(번역·그림분석)을 적용할 논문들. 체크박스로만 담긴다 — 실수로 전체가 도는 걸 막는다. */
  checkedIds: string[]
  readerOpen: boolean
  /** AI 챗봇 좌측 패널 — 라이브러리에서도 원문을 읽는 중에도 같은 패널을 연다 */
  chatOpen: boolean
  /** 서버 상태(유료 잠금·번역 공급자·비용 어림값). 못 읽었으면 null */
  health: Health | null

  refreshDocuments: () => Promise<void>
  refreshHealth: () => Promise<void>
  select: (id: string | null) => void
  toggleChecked: (id: string) => void
  clearChecked: () => void
  openReader: (id: string) => void
  closeReader: () => void
  openChat: () => void
  closeChat: () => void
}

export const useApp = create<AppState>((set, get) => ({
  documents: [],
  selectedId: null,
  checkedIds: [],
  readerOpen: false,
  chatOpen: false,
  health: null,

  refreshHealth: async () => {
    try {
      set({ health: await api.getHealth() })
    } catch {
      set({ health: null })
    }
  },
  refreshDocuments: async () => {
    const docs = await api.listDocuments()
    set({ documents: docs })
    // 선택된 문서가 없으면 처리 완료된 첫 문서를 자동 선택
    if (!get().selectedId) {
      const ready = docs.find((d) => d.status === 'ready')
      if (ready) set({ selectedId: ready.doc_id })
    }
  },
  select: (id) => set({ selectedId: id }),
  toggleChecked: (id) =>
    set((s) => ({
      checkedIds: s.checkedIds.includes(id)
        ? s.checkedIds.filter((x) => x !== id)
        : [...s.checkedIds, id],
      selectedId: id, // 마지막으로 만진 논문을 시각자료·챗봇 범위의 기준으로 삼는다
    })),
  clearChecked: () => set({ checkedIds: [] }),
  openReader: (id) => set({ selectedId: id, readerOpen: true }),
  closeReader: () => set({ readerOpen: false }),
  openChat: () => set({ chatOpen: true }),
  closeChat: () => set({ chatOpen: false }),
}))

/** 처리 중인 문서가 있으면 폴링해서 진행률을 갱신한다. */
export function useDocPolling() {
  const { documents, refreshDocuments } = useApp()
  const busy = documents.some(
    (d) => d.status !== 'ready' && d.status !== 'failed',
  )
  return { busy, refreshDocuments }
}
