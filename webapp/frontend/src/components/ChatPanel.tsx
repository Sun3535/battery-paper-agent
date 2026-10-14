// 논문 검색 패널.
//
// mode=local  : SQLite FTS5 로컬 검색 (기본). 비용 0원 · 외부 호출 없음.
//               AI 요약 대신 **매칭된 원문 구절**을 논문별로 묶어 보여준다.
// mode=cloud  : Vertex AI Search (LLM 그라운딩 요약). 크레딧 차감.
// mode=locked : 유료 하드락으로 cloud 차단됨.
//
// 디자인: 질문은 보라 말풍선, AI 응답은 말풍선이 아니라 "구조화된 기록"(인디고 좌측 선 + 옅은 틴트),
//         근거 구절은 흰 입체 카드.

import { SearchOutlined, SendOutlined } from '@ant-design/icons'
import { Button, Input, Segmented, Spin } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api, type ChatResponse } from '../api'
import { useApp } from '../store'
import { T } from '../theme'

interface Turn {
  question: string
  res?: ChatResponse
  error?: string
}

/** 백엔드가 「…」로 감싸 보낸 매칭 부분을 강조 렌더 */
function Highlight({ text }: { text: string }) {
  const parts = text.split(/(「[^」]*」)/g)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('「') && p.endsWith('」') ? (
          <mark key={i} className="pa-chat-mark">
            {p.slice(1, -1)}
          </mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  )
}

export function ChatPanel() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  // true면 특정 논문에 집중. 기본값은 아래 effect 가 상황에 맞춰 정한다.
  const [scoped, setScoped] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const openReader = useApp((s) => s.openReader)
  const selectedId = useApp((s) => s.selectedId)
  const checkedIds = useApp((s) => s.checkedIds)
  const documents = useApp((s) => s.documents)
  const readerOpen = useApp((s) => s.readerOpen)

  // 무엇에 집중할지: 논문을 읽는 중이면 **그 논문**, 아니면 라이브러리에서 체크한 논문들.
  const reading = readerOpen && !!selectedId
  const focusIds = reading ? [selectedId] : checkedIds.length ? checkedIds : selectedId ? [selectedId] : []
  const focusDocs = documents.filter((d) => focusIds.includes(d.doc_id))
  // 기본은 '이 논문만'(호야 지시 2026-10-14) — 논문을 읽는 중이거나 체크한 논문이 있을 때.
  // 아무것도 고르지 않고 라이브러리에서 열었으면 전체 검색이 기본이다(엉뚱한 한 편에 묶이지 않게).
  // 사람이 직접 바꾼 선택은 상황(읽는 논문·체크)이 바뀌기 전까지 그대로 둔다.
  useEffect(() => {
    setScoped(reading || checkedIds.length > 0)
  }, [reading, selectedId, checkedIds.length])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setTurns((t) => [...t, { question: q }])
    setLoading(true)
    try {
      const res = await api.chat(q, scoped ? focusIds : null)
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, res } : x)))
    } catch (e) {
      setTurns((t) =>
        t.map((x, i) => (i === t.length - 1 ? { ...x, error: (e as Error).message } : x)),
      )
    } finally {
      setLoading(false)
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, overflowY: 'auto', marginRight: -6, paddingRight: 6 }}>
        {turns.length === 0 && (
          <div style={{ textAlign: 'center', marginTop: 70, color: T.textFaint }}>
            <div className="pa-drop-ico" style={{ margin: '0 auto 16px' }}>
              <SearchOutlined />
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.9 }}>
              {scoped && focusDocs.length
                ? focusDocs.length > 1
                  ? `체크한 ${focusDocs.length}편을 읽고 답합니다.`
                  : '지금 보는 논문 한 편을 읽고 답합니다.'
                : '수집한 논문 전체에서 검색합니다.'}
              <br />
              <span style={{ color: T.textFaint }}>예: coulombic efficiency / 음극재 / dendrite</span>
            </div>
            <div style={{ fontSize: 11.5, color: T.textFaint, marginTop: 14 }}>
              로컬 검색 · 비용 0원 · 외부 전송 없음
            </div>
          </div>
        )}

        {turns.map((t, i) => {
          const locked = t.res?.mode === 'locked'
          return (
            <div key={i} style={{ marginBottom: 22 }}>
              <div className="pa-q">{t.question}</div>

              {t.error && (
                <div
                  className="ai-response"
                  style={{ marginTop: 10, borderLeftColor: T.danger, color: T.danger, fontSize: 13 }}
                >
                  {t.error}
                </div>
              )}

              {t.res && (
                <div
                  className="ai-response"
                  style={{
                    marginTop: 10,
                    fontSize: 14,
                    lineHeight: 1.7,
                    ...(locked
                      ? { borderLeftColor: T.warning, background: '#fffbeb' }
                      : {}),
                  }}
                >
                  <div
                    style={{
                      fontSize: 10.5,
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                      color: locked ? T.warning : t.res.mode === 'cloud' ? T.ai : T.success,
                      marginBottom: 8,
                    }}
                  >
                    {locked
                      ? 'LOCKED'
                      : t.res.mode === 'cloud'
                        ? 'AI AGENT · 크레딧 사용'
                        : t.res.mode === 'api'
                          ? 'AI 요약 · API 키'
                          : t.res.mode === 'fallback'
                            ? '자격증명 없음'
                            : 'LOCAL SEARCH · 비용 0원'}
                    {t.res.scope && (
                      <span style={{ color: T.primary, marginLeft: 6 }}>
                        · 「{t.res.scope}」 한정
                      </span>
                    )}
                  </div>

                  {/* 유료로 만든 그림 분석이 이 답변에 실제로 쓰였음을 보여준다 */}
                  {!!t.res.figures_used?.length && (
                    <div
                      style={{
                        fontSize: 11,
                        color: T.success,
                        marginBottom: 8,
                        paddingBottom: 6,
                        borderBottom: `1px dashed ${T.border}`,
                        lineHeight: 1.6,
                      }}
                    >
                      🔬 그림 분석 {t.res.figures_used.length}건 활용: {t.res.figures_used.join(', ')}
                    </div>
                  )}

                  {/* 이번 답변에 참고된 과거 기억 — 무엇이 주입됐는지(=비용) 투명하게 */}
                  {!!t.res.memories_used?.length && (
                    <div
                      style={{
                        fontSize: 11,
                        color: T.textFaint,
                        marginBottom: 8,
                        paddingBottom: 6,
                        borderBottom: `1px dashed ${T.border}`,
                        lineHeight: 1.6,
                      }}
                    >
                      💡 과거 대화 {t.res.memories_used.length}건 참고:{' '}
                      {t.res.memories_used.map((q) => `"${q.slice(0, 26)}"`).join(', ')}
                    </div>
                  )}

                  <div style={{ whiteSpace: 'pre-wrap', color: T.text }}>{t.res.answer}</div>

                  {/* 로컬 검색: 논문별 매칭 구절 */}
                  {t.res.results.map((g) => (
                    <div key={g.doc_id} className="pa-hit">
                      <div
                        onClick={() => openReader(g.doc_id)}
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: T.primaryDeep,
                          cursor: 'pointer',
                          marginBottom: 6,
                          wordBreak: 'break-all',
                        }}
                      >
                        📄 {g.title} <span style={{ color: T.textFaint }}>— 읽기</span>
                      </div>
                      {g.passages.map((p, j) => (
                        <div
                          key={j}
                          style={{
                            fontSize: 12,
                            color: T.textDim,
                            lineHeight: 1.7,
                            padding: '4px 0',
                            display: 'flex',
                            gap: 8,
                          }}
                        >
                          <span style={{ color: T.textFaint, flexShrink: 0 }}>p{p.page}</span>
                          <span>
                            <Highlight text={p.text} />
                          </span>
                        </div>
                      ))}
                    </div>
                  ))}

                  {/* 클라우드 모드: LLM 요약의 근거 문서 */}
                  {!!t.res.citations.length && (
                    <div
                      style={{ marginTop: 12, borderTop: `1px solid ${T.border}`, paddingTop: 10 }}
                    >
                      <div style={{ fontSize: 10, color: T.textFaint, marginBottom: 6 }}>
                        SOURCES
                      </div>
                      {t.res.citations.map((c, j) => (
                        <div key={j} style={{ fontSize: 12, color: T.textDim, padding: '3px 0' }}>
                          <span style={{ color: T.success }}>[{j + 1}]</span> {c.title}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {loading && <Spin style={{ display: 'block', margin: '16px auto' }} />}
        <div ref={bottomRef} />
      </div>

      {/* 질문 범위 — 전체 라이브러리 vs 선택한 논문 1편 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          paddingTop: 12,
        }}
      >
        <Segmented
          size="small"
          value={scoped ? 'focus' : 'all'}
          onChange={(v) => setScoped(v === 'focus')}
          options={[
            { label: `전체 (${documents.length}편)`, value: 'all' },
            {
              label: focusIds.length > 1 ? `체크한 ${focusIds.length}편` : '이 논문만',
              value: 'focus',
              disabled: !focusIds.length,
            },
          ]}
        />
        <span
          style={{
            fontSize: 11,
            color: scoped ? T.primary : T.textFaint,
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={focusDocs.map((d) => d.title).join('\n')}
        >
          {scoped
            ? focusDocs.length
              ? `📄 ${focusDocs.map((d) => d.title).join(' · ')} — 집중 (나머지는 참고)`
              : '라이브러리에서 논문을 체크하세요'
            : '라이브러리 전체에서 검색'}
        </span>
      </div>

      <div className="pa-chat-input">
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder={scoped && focusDocs.length ? '이 논문에 대해 물어보기…' : '논문 전체에서 검색…'}
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading} />
      </div>
    </div>
  )
}
