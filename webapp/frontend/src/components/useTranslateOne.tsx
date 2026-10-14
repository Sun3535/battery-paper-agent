// 논문 한 편을 바로 번역 — 서가 표지의 [한글 번역] 과 리더의 [지금 번역] 이 같은 길을 쓴다.
// 유료라서 언제나 확인창(예상 비용)을 먼저 띄운다.
// 유료 API 가 잠겨 있으면 확인창 대신 **제한 안내**를 띄운다(호야 지시 2026-10-14) — usePaidLock.

import { App } from 'antd'
import { useState } from 'react'
import { api, type DocumentMeta } from '../api'
import { translateEstimate } from '../cost'
import { useApp } from '../store'
import { T } from '../theme'

/** 유료 API 잠금 상태. 유료 동작(번역·그림분석)을 시작하기 전에 `blocked()` 로 거른다. */
export function usePaidLock() {
  const { modal } = App.useApp()
  const health = useApp((s) => s.health)
  // 서버 상태를 아직 못 읽었으면 잠긴 것으로 단정하지 않는다(서버가 어차피 한 번 더 막는다)
  const locked = health ? !health.paid_apis_enabled : false

  /** 최신 상태를 다시 읽어, 잠겨 있으면 안내를 띄우고 true 를 돌려준다(= 여기서 멈출 것).
      what 은 조사까지 붙여 넘긴다: '번역을', '그림·표 AI 분석을' */
  const blocked = async (what: string): Promise<boolean> => {
    await useApp.getState().refreshHealth()
    const h = useApp.getState().health
    if (!h || h.paid_apis_enabled) return false
    modal.warning({
      title: h.offline_mode ? '완전 로컬 모드입니다' : '유료 API가 잠겨 있습니다',
      width: 440,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          {h.offline_mode ? (
            <>외부와 통신하지 않는 모드라 {what} 실행할 수 없습니다.</>
          ) : (
            <>
              잠금 상태에서는 {what} 실행할 수 없습니다.
              <br />
              위 메뉴바의 <b>「🔒 유료 API 잠김」</b> 배지를 눌러 켠 뒤 다시 시도하세요.
            </>
          )}
          <div style={{ marginTop: 6, fontSize: 12, color: T.textFaint }}>
            원문 읽기 · 검색 · 이미 번역한 논문 열람은 잠금과 상관없이 됩니다.
          </div>
        </div>
      ),
      okText: '확인',
    })
    return true
  }

  return { locked, blocked }
}

export function useTranslateOne() {
  const { message, modal } = App.useApp()
  const refreshDocuments = useApp((s) => s.refreshDocuments)
  const lock = usePaidLock()
  const [starting, setStarting] = useState(false)

  const start = async (doc: DocumentMeta) => {
    if (await lock.blocked('번역을')) return
    const est = translateEstimate(useApp.getState().health, [doc])
    modal.confirm({
      title: '이 논문을 한국어로 번역할까요?',
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ color: T.textDim, marginBottom: 6 }}>{doc.title.slice(0, 110)}</div>
          예상 비용 <b style={{ color: T.warning }}>약 ₩{est.krw.toLocaleString()}</b>{' '}
          <span style={{ color: T.textFaint }}>({est.basis})</span>
          <div style={{ marginTop: 6, fontSize: 12, color: T.textFaint }}>
            한 번 번역한 논문은 저장되어 다시 열 때 비용이 들지 않습니다.
          </div>
        </div>
      ),
      okText: '번역 실행',
      cancelText: '취소',
      onOk: async () => {
        setStarting(true)
        try {
          const r = await api.translateDoc(doc.doc_id)
          if (r.started) message.success(r.message)
          else message.warning(r.message)
          await refreshDocuments()
          // 실행 직후에는 상태가 아직 안 바뀌었을 수 있다 → 한 번 더 확인해 진행 표시가 켜지게 한다
          setTimeout(refreshDocuments, 1500)
        } catch (e) {
          message.error((e as Error).message)
        } finally {
          setStarting(false)
        }
      },
    })
  }

  return { start, starting, locked: lock.locked }
}
