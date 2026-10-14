// 논문 라이브러리 — 히어로 + 검색 + 통계 + 업로드 + 서가 (Stitch "Paper E-book Reader Redesign · Violet").
//
// 표지는 크게 깐다 — 좁은 칼럼에서는 표지 글자가 안 보였다(2026-07-28 호야 지적).
// 통계 숫자는 전부 /api/documents 가 준 값에서 센다(지어낸 숫자 없음).

import {
  CaretRightOutlined,
  CheckOutlined,
  CloseOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  InboxOutlined,
  LockOutlined,
  ReadOutlined,
  SearchOutlined,
  TranslationOutlined,
} from '@ant-design/icons'
import { App, Button, Checkbox, Progress, Tooltip, Upload } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type DocumentMeta } from '../api'
import { translateEstimate, translateUnitLabel } from '../cost'
import { useApp } from '../store'
import { T } from '../theme'
import { usePaidLock, useTranslateOne } from './useTranslateOne'

const STATUS: Record<DocumentMeta['status'], { label: string; color: string }> = {
  pending: { label: '대기', color: T.textFaint },
  extracting: { label: '추출 중', color: T.primary },
  translating: { label: '번역 중', color: T.ai },
  indexing: { label: '색인 중', color: T.ai },
  // '완료'는 무료 단계(추출·색인)가 끝났다는 뜻일 뿐이다. 유료 산출물(번역·그림분석)은
  // 아래 별도 배지로 따로 표시한다 — 어느 버튼에 이미 돈을 냈는지 헷갈리면 안 되므로.
  ready: { label: '수집 완료', color: T.success },
  failed: { label: '실패', color: T.danger },
}

// 그림분석 1편당 대략 비용 (확인 창에 보여줄 값). 번역 비용은 공급자마다 달라 cost.ts 가 계산한다.
const ANALYZE_PER_PAPER = 30

/** 이미 돈을 낸 산출물인지 — 카드 배지와 버튼 잠금이 같은 판정을 쓴다 */
const isPaidFor = (d: DocumentMeta, kind: 'translate' | 'analyze') =>
  kind === 'translate' ? !!d.translated : !!d.analyzed

export function LibraryView() {
  const { message, modal } = App.useApp()
  const { documents, checkedIds, toggleChecked, clearChecked, openReader, refreshDocuments, health } =
    useApp()
  const translateOne = useTranslateOne()
  const lock = usePaidLock()
  const [optTranslate, setOptTranslate] = useState(false)
  const [optAnalyze, setOptAnalyze] = useState(false)
  const [filter, setFilter] = useState('')

  const q = filter.trim().toLowerCase()
  const shown = q
    ? documents.filter(
        (d) => d.title.toLowerCase().includes(q) || (d.filename ?? '').toLowerCase().includes(q),
      )
    : documents

  const checkedDocs = documents.filter((d) => checkedIds.includes(d.doc_id))
  /** 체크한 것 중 이미 돈을 낸 논문들 — 하나라도 있으면 그 버튼을 아예 막는다.
      (호야 지시 2026-07-28: 한 번 지불한 논문에 재과금이 나갈 여지를 없앤다) */
  const alreadyPaid = {
    translate: checkedDocs.filter((d) => isPaidFor(d, 'translate')),
    analyze: checkedDocs.filter((d) => isPaidFor(d, 'analyze')),
  }

  /** 체크된 논문에만 실행. 몇 편·얼마인지 확인받고 나서 진행한다(실수로 91편 도는 사고 방지). */
  const run = async (kind: 'translate' | 'analyze') => {
    // 유료 API 가 잠겨 있으면 여기서 멈추고 제한 안내를 띄운다(확인창·비용을 보여 주지 않는다)
    if (await lock.blocked(kind === 'translate' ? '번역을' : '그림·표 AI 분석을')) return
    const targets = documents.filter((d) => checkedIds.includes(d.doc_id) && d.status === 'ready')
    if (!targets.length) {
      return message.warning('논문 카드의 체크박스로 대상을 먼저 선택하세요. (카드를 클릭하면 체크)')
    }
    if (alreadyPaid[kind].length) {
      return message.warning('이미 처리한 논문이 선택돼 있습니다. 그 논문의 체크를 풀어주세요.')
    }
    const label = kind === 'translate' ? '한국어 번역' : '그림·표 AI 분석'
    const est =
      kind === 'translate'
        ? translateEstimate(health, targets)
        : { krw: targets.length * ANALYZE_PER_PAPER, basis: `편당 ~₩${ANALYZE_PER_PAPER}` }

    modal.confirm({
      title: `${label} — ${targets.length}편 실행`,
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 8 }}>
            예상 비용 <b style={{ color: T.warning }}>약 ₩{est.krw.toLocaleString()}</b>
            <span style={{ color: T.textFaint }}> ({est.basis})</span>
          </div>
          <div
            style={{
              maxHeight: 150,
              overflowY: 'auto',
              fontSize: 12,
              color: T.textDim,
              border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm,
              padding: '6px 10px',
            }}
          >
            {targets.map((t) => (
              <div key={t.doc_id} style={{ padding: '2px 0' }}>
                · {t.title.slice(0, 52)}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: T.textFaint }}>
            이미 처리된 부분은 다시 과금되지 않습니다.
          </div>
        </div>
      ),
      okText: `${targets.length}편 실행`,
      cancelText: '취소',
      onOk: async () => {
        let started = 0
        for (const t of targets) {
          try {
            const r =
              kind === 'translate'
                ? await api.translateDoc(t.doc_id)
                : await api.analyzeFigures(t.doc_id)
            if (r.locked) {
              message.warning(r.message)
              break
            }
            if (r.started) started += 1
          } catch (e) {
            message.error(`${t.title.slice(0, 20)}…: ${(e as Error).message}`)
          }
        }
        message.success(`${started}편 처리 시작`)
        refreshDocuments()
      },
    })
  }

  const sum = (f: (d: DocumentMeta) => number | undefined) =>
    documents.reduce((n, d) => n + (f(d) ?? 0), 0)
  const stats: { icon: ReactNode; value: number; unit: string; label: string }[] = [
    { icon: <ReadOutlined />, value: documents.length, unit: '편', label: '보관 논문' },
    {
      icon: <TranslationOutlined />,
      value: documents.filter((d) => d.translated).length,
      unit: '편',
      label: '한국어 번역본',
    },
    {
      icon: <ExperimentOutlined />,
      value: sum((d) => d.analyzed_figures),
      unit: '장',
      label: 'AI가 분석한 그림·표',
    },
    { icon: <FileTextOutlined />, value: sum((d) => d.page_count), unit: '쪽', label: '읽을 수 있는 분량' },
  ]

  const shelfRef = useRef<HTMLDivElement>(null)
  const goShelf = () => shelfRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return (
    <div>
      {/* ── 히어로 ─────────────────────────────────────── */}
      <section className="pa-hero">
        <div className="pa-eyebrow pa-rise">
          <span className="pip">E-BOOK</span>
          배터리 논문 라이브러리
        </div>
        <h1 className="pa-rise" style={{ ['--i' as string]: 1 }}>
          AI 시대에 문을 연,
          <br />
          <span className="grad">논문책방</span>
        </h1>
        <p className="sub pa-rise" style={{ ['--i' as string]: 2 }}>
          내가 미국인이었다면 논문이 쉽게 읽혔을까? 그 질문에서 시작했습니다.
        </p>

        <div className="pa-searchbar pa-rise" style={{ ['--i' as string]: 3 }}>
          <SearchOutlined className="search-icon" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && goShelf()}
            placeholder="제목으로 논문 찾기"
            aria-label="제목으로 논문 찾기"
          />
          {q && (
            <>
              <span className="hint">{shown.length}편</span>
              <button type="button" className="clear" onClick={() => setFilter('')} title="지우기">
                <CloseOutlined />
              </button>
            </>
          )}
          <button type="button" className="pa-pill-primary" onClick={goShelf}>
            찾기
          </button>
        </div>
      </section>

      {/* ── 통계 ───────────────────────────────────────── */}
      <div className="pa-stats">
        {stats.map((s, i) => (
          <div key={s.label} className="pa-stat pa-rise" style={{ ['--i' as string]: 4 + i }}>
            <div className="ico">{s.icon}</div>
            <div>
              <div className="num">
                <CountUp value={s.value} />
                <small>{s.unit}</small>
              </div>
              <div className="lbl">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ── 업로드 + 유료 작업 ───────────────────────────
          Dragger 는 기본이 height:100% 라 부모 높이만큼 늘어난다(화면을 다 먹는다).
          .pa-intake 가 높이를 고정해 서가가 위로 올라오게 한다. */}
      <div className="pa-card pa-intake pa-rise" style={{ ['--i' as string]: 8 }}>
        <Upload.Dragger
          multiple
          accept=".pdf"
          showUploadList={false}
          className="paper-dropzone"
          customRequest={async (opt) => {
            try {
              const res = await api.upload(opt.file as File, {
                translate: optTranslate,
                analyze: optAnalyze,
              })
              message.success(`${res.title} — 처리 시작`)
              opt.onSuccess?.(res)
              refreshDocuments()
            } catch (e) {
              message.error(`업로드 실패: ${(e as Error).message}`)
              opt.onError?.(e as Error)
            }
          }}
        >
          <div className="pa-drop-inner">
            <div className="pa-drop-ico">
              <InboxOutlined />
            </div>
            <div>
              <div className="pa-drop-title">논문 PDF를 끌어다 놓으세요</div>
              <div className="pa-drop-sub">본문·그림·표 추출과 검색 색인은 항상 무료입니다</div>
            </div>
          </div>
        </Upload.Dragger>

        {/* 왼쪽 [실행] = "지금 카드에서 체크한 논문"에만 실행 (개수·비용 확인 후)
            오른쪽 체크박스 = "앞으로 업로드할 논문"에 자동 적용할지 */}
        <div className={`pa-actionbar${checkedIds.length ? ' has-sel' : ''}`}>
          <span className="sel">
            {checkedIds.length ? (
              <>
                <b>{checkedIds.length}편</b> 선택됨
                <a onClick={clearChecked}>선택 해제</a>
              </>
            ) : (
              '아래 카드를 클릭해 대상을 선택하세요'
            )}
          </span>

          <span className="sep" />

          <PaidButton
            label="한국어 번역"
            price={translateUnitLabel(health)}
            paidLocked={lock.locked}
            blocked={alreadyPaid.translate}
            disabled={!checkedIds.length}
            onRun={() => run('translate')}
          />
          <PaidButton
            label="그림·표 AI 분석"
            price="~₩30/편"
            paidLocked={lock.locked}
            blocked={alreadyPaid.analyze}
            disabled={!checkedIds.length}
            onRun={() => run('analyze')}
          />

          <span className="auto">
            <Tooltip title="앞으로 새로 업로드하는 논문에 자동 적용할 항목입니다(기존 논문과 무관).">
              <span>새 업로드 자동:</span>
            </Tooltip>
            <Checkbox checked={optTranslate} onChange={(e) => setOptTranslate(e.target.checked)}>
              번역
            </Checkbox>
            <Checkbox checked={optAnalyze} onChange={(e) => setOptAnalyze(e.target.checked)}>
              그림분석
            </Checkbox>
          </span>
        </div>
      </div>

      {/* ── 서가 ─────────────────────────────────────────── */}
      <div className="pa-section-head" ref={shelfRef} style={{ scrollMarginTop: 96 }}>
        <h2>논문 라이브러리</h2>
        <span className="badge">{q ? `${shown.length} / ${documents.length}편` : `${documents.length}편`}</span>
        <span className="cap">카드를 클릭해 선택, 더블클릭하면 E-book으로 읽습니다</span>
      </div>

      <div className="pa-grid">
        {shown.map((d, i) => {
          const busy = d.status !== 'ready' && d.status !== 'failed'
          const st = STATUS[d.status]
          const checked = checkedIds.includes(d.doc_id)
          return (
            <div
              key={d.doc_id}
              data-paper-card
              className={`pa-tile pa-rise${checked ? ' checked' : ''}`}
              // 첫 화면에 보이는 두 줄만 차례로 떠오른다(91장 전부 기다리게 하지 않는다)
              style={{ ['--i' as string]: Math.min(i, 10) }}
              // 한 번 클릭 = 체크 토글 / 두 번 = 원문 읽기
              onClick={() => toggleChecked(d.doc_id)}
              onDoubleClick={() => d.status === 'ready' && openReader(d.doc_id)}
              title={`${d.title}\n\n클릭: 선택 · 더블클릭: 원문 보기`}
            >
              {/* 표지 — PDF 1페이지. 3:4 비율로 크게 깔아 제목·초록이 읽히게 */}
              <div className="pa-cover">
                {d.cover_url && <img src={d.cover_url} alt="" loading="lazy" />}

                {/* 좌측 상단 체크 — 유료 작업 대상 표시 */}
                <div className="pa-check">{checked && <CheckOutlined />}</div>

                {/* 표지에 마우스를 올리면 나오는 버튼 — 번역(아직 안 한 논문만) · 읽기 */}
                {d.status === 'ready' && (
                  <div className="pa-cover-actions" onDoubleClick={(e) => e.stopPropagation()}>
                    {!d.translate_complete && (
                      <button
                        type="button"
                        className={`pa-cover-btn translate${lock.locked ? ' locked' : ''}`}
                        disabled={translateOne.starting}
                        title={
                          lock.locked
                            ? '유료 API가 잠겨 있어 번역할 수 없습니다 (누르면 안내)'
                            : '이 논문을 한국어로 번역 (유료 — 누르면 비용을 먼저 확인합니다)'
                        }
                        onClick={(e) => {
                          e.stopPropagation()
                          translateOne.start(d)
                        }}
                      >
                        {lock.locked ? <LockOutlined /> : <TranslationOutlined />}
                        한글 번역
                      </button>
                    )}
                    <button
                      type="button"
                      className="pa-cover-btn pa-read"
                      onClick={(e) => {
                        e.stopPropagation()
                        openReader(d.doc_id)
                      }}
                    >
                      <ReadOutlined />
                      읽기
                    </button>
                  </div>
                )}
              </div>

              <div className="pa-tile-title">{d.title}</div>

              <div className="pa-tile-meta">
                <span className="dot" style={{ background: st.color }} />
                <span style={{ color: st.color, fontWeight: 500 }}>{st.label}</span>
                {d.page_count > 0 && <span>· {d.page_count}p</span>}
              </div>

              {/* 유료 산출물 — 무엇에 이미 돈을 냈는지 한눈에 (버튼이 두 개라 구분이 필수) */}
              {d.status === 'ready' && (d.translated || d.analyzed) && (
                <div className="pa-chips">
                  {d.translated && (
                    <DoneChip
                      text={d.translate_complete ? '번역 완료' : `번역 ${d.translated_blocks}/${d.text_blocks}`}
                      color={T.primaryDeep}
                    />
                  )}
                  {d.analyzed && (
                    <DoneChip
                      text={
                        d.analyze_complete
                          ? '그림분석 완료'
                          : `그림분석 ${d.analyzed_figures}/${d.figure_blocks}`
                      }
                      color={T.success}
                    />
                  )}
                </div>
              )}

              {busy && (
                <Progress
                  percent={d.progress}
                  size="small"
                  showInfo={false}
                  strokeColor={{ from: '#8b5cf6', to: '#6366f1' }}
                  trailColor={T.border}
                  style={{ margin: '8px 4px 0', width: 'auto' }}
                />
              )}
            </div>
          )
        })}
      </div>

      {!shown.length && (
        <div className="pa-empty">
          {documents.length ? '검색 결과가 없습니다' : '아직 논문이 없습니다 — PDF를 끌어다 놓으세요'}
        </div>
      )}
    </div>
  )
}

/** 숫자가 0에서 차오른다. 움직임을 줄이도록 설정한 사람에게는 바로 최종값을 보여 준다. */
function CountUp({ value }: { value: number }) {
  const [n, setN] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return setN(value)
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 900)
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <>{n.toLocaleString()}</>
}

/** 이미 지불한 산출물 표시 — '완료' 하나로 뭉뚱그리지 않는다 */
function DoneChip({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="pa-chip"
      style={{ color, background: `${color}14`, boxShadow: `inset 0 0 0 1px ${color}33` }}
    >
      ✓ {text}
    </span>
  )
}

/** 유료 실행 버튼 — 체크 목록에 '이미 처리한 논문'이 하나라도 있으면 잠긴다(재과금 차단) */
function PaidButton(props: {
  label: string
  price: string
  blocked: DocumentMeta[]
  disabled: boolean
  /** 유료 API 잠금 — 누르면 실행 대신 제한 안내가 뜬다 */
  paidLocked: boolean
  onRun: () => void
}) {
  if (props.paidLocked) {
    return (
      <Tooltip title="유료 API가 잠겨 있습니다 — 메뉴바의 잠금 배지를 눌러 켜면 실행할 수 있습니다">
        <Button className="pa-run paid-locked" icon={<LockOutlined />} onClick={props.onRun}>
          {props.label} <span className="price">· 잠김</span>
        </Button>
      </Tooltip>
    )
  }
  const locked = props.blocked.length > 0
  const tip = locked
    ? `이미 처리된 논문이 선택돼 있어 잠겼습니다 (재과금 방지): ${props.blocked
        .map((d) => d.title.slice(0, 28))
        .join(', ')}`
    : props.disabled
      ? '카드를 클릭해 대상을 선택하세요'
      : ''
  return (
    <Tooltip title={tip}>
      <Button
        className="pa-run"
        icon={<CaretRightOutlined />}
        disabled={props.disabled || locked}
        onClick={props.onRun}
      >
        {props.label} <span className="price">{locked ? '· 처리됨' : props.price}</span>
      </Button>
    </Tooltip>
  )
}
