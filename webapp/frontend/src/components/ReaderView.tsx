// E-book 리더 — 블록을 order 순서대로 렌더하면 번역문 사이에 원본 그림이 원래 자리에 들어간다.
//
// 디자인(Stitch "Paper E-book Reader Redesign · Violet"): 오른쪽에서 밀려 나오는 흰 종이 한 장,
// 가운데 한 단 본문, 왼쪽에 떠 있는 유리 도구 막대(보기·글자·배경·챗봇), 맨 위에 읽은 만큼 차는 보라 선.
// 배경은 밝게(기본)/어둡게 를 고를 수 있다 — 오래 읽을 때 눈부심은 사람마다 달라서.
// 이미지 원칙: width 100% + height auto만. 잘라내기·비율변경·필터 없음.
//
// 구획(호야 지시 2026-10-14: "제목·저자, 초록, 본 내용의 구분이 어렵다"):
//   표제(제목 + 저자·소속) → 초록 상자 → 본문 → 참고문헌 상자. 서로 다른 칸·색으로 나눈다.
//   구획은 화면에서 추정한다(초록은 "ABSTRACT" 로 시작하는 블록). 못 찾으면 나누지 않고 예전처럼 한 줄로 보여 준다.

import { MessageOutlined, TranslationOutlined, WarningOutlined } from '@ant-design/icons'
import { Drawer, Empty, Progress, Spin, Table } from 'antd'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type Block } from '../api'
import { glossify } from '../glossary'
import { useApp } from '../store'
import { useTranslateOne } from './useTranslateOne'

type Lang = 'ko' | 'en' | 'both'

/** 한글 뷰의 영문 용어에 회색 한글 gloss(ruby)를 깐다. 원문(en) 뷰는 그대로 둔다. */
function ko(text: string): ReactNode {
  return glossify(text)
}

/** 섹션 제목처럼 보이는 짧은 줄은 헤딩으로 (E-book 가독성) */
function isHeading(b: Block): boolean {
  const t = (b.text_en || '').trim()
  return (
    !b.is_caption &&
    t.length < 60 &&
    /^(?:\d+\.?\s+)?[A-Z가-힣]/.test(t) &&
    !t.endsWith('.') &&
    t.split(' ').length <= 8
  )
}

// ── 구획 나누기 ──────────────────────────────────────────────
// PDF 에서 뽑은 블록에는 "여기가 초록" 이라는 표시가 없다. 그래서 화면에서 추정한다.
//   ① "ABSTRACT" 로 시작하는 글           → 초록 (가장 확실)
//   ② 글 중간에 "Abstract" 가 박힌 덩어리  → 그 앞은 표제, 뒤는 초록 (제목·저자와 한 덩어리로 뽑힌 논문)
//   ③ 표시가 전혀 없는 논문               → 서론 앞, 첫 두 쪽의 첫 '줄글 문단' 을 초록으로 **추정** (이름표에 추정이라고 적는다)
// 어느 것도 못 찾거나 찾은 글이 너무 짧으면 나누지 않는다 — 틀린 칸에 넣느니 예전처럼 한 줄로 보여 준다.
const ABSTRACT_RE = /^\s*(?:abstract|초록)\b[\s:.\-–—]*/i
const ABSTRACT_INLINE_RE = /\babstract\b[\s:.\-–—]*/i
const INTRO_RE = /^\s*(?:\d+\.?|[IVX]+\.)?\s*introduction\b/i
const KEYWORDS_RE = /^\s*key\s?words?\b/i
const REFS_RE = /^\s*(?:references|bibliography|notes and references|literature cited|참고\s?문헌)\b[\s:.\-–—]*/i
const AFFIL_RE =
  /\b(?:University|Institute|Department|Laboratory|College|Correspond\w*|E-?mail|licen[sc]ed?|Creative Commons|unedited|Received|Accepted)\b|©|@/gi

const isText = (b: Block) => b.kind === 'text' && !b.is_caption
const en = (b: Block) => (b.text_en || '').replace(/[\u200b-\u200d\ufeff]/g, '').trim()
const squash = (s: string) => s.replace(/\s+/g, ' ').trim()

/** 표제 칸에 큰 제목을 따로 보여 주므로, 첫 줄에 붙어 온 제목은 떼어 낸다(저자·소속만 남긴다). */
function withoutTitle(text: string, title: string): string {
  const t = squash(text)
  const head = squash(title)
  if (head && t.toLowerCase().startsWith(head.toLowerCase())) return t.slice(head.length).trim()
  return t
}

const NOT_ABSTRACT_RE =
  /^(?:main|introduction|background|disclaimer)\b|sponsored by an agency|United States Government|warrant(?:y|ies)/i

/** 저자 목록·소속·저작권 문구가 아니라 '줄글 문단' 처럼 보이는가 (③ 추정용).
    서가 91편으로 점검하며 걸러 낸 것: 저자 목록(쉼표·윗첨자 숫자 범벅), 소속으로 시작하는 덩어리,
    앞 단에서 이어진 문장 조각(소문자로 시작), 보고서의 면책 문구, "Main"·"Introduction" 으로 시작하는 본문. */
function looksLikeProse(t: string): boolean {
  if (!/^[A-Z]/.test(t) || NOT_ABSTRACT_RE.test(t)) return false
  const sentences = (t.match(/[a-z)\]]\.\s+[A-Z]/g) || []).length
  const digits = (t.match(/\d/g) || []).length / t.length
  const affil = (t.match(AFFIL_RE) || []).length
  const lead = t.slice(0, 200)
  const listy = (lead.match(/[,\d]/g) || []).length / lead.length // 저자 목록은 쉼표·숫자가 촘촘하다
  return sentences >= 2 && digits < 0.05 && affil < 2 && listy < 0.08
}

interface Piece {
  key: string
  en: string
  ko: string
}
interface Sections {
  front: string[] // 초록 앞의 글(저자·소속·게재 정보) — 고유명사라 원문 그대로
  abstract: Piece[]
  guessed: boolean // ③ 으로 추정한 초록인가
  body: Block[]
  refs: Block[]
  split: boolean // 구획을 나눴는가
}

function splitSections(blocks: Block[], title: string): Sections {
  const none: Sections = { front: [], abstract: [], guessed: false, body: blocks, refs: [], split: false }
  // 앞부분의 글 블록 자리(표지가 딸린 논문이 있어 5쪽·40블록까지 본다)
  const head: number[] = []
  for (let i = 0; i < blocks.length && head.length < 40; i++) {
    if (isText(blocks[i]) && blocks[i].page <= 5) head.push(i)
  }
  const introAt = head.find((i) => INTRO_RE.test(en(blocks[i])))
  const beforeIntro = head.filter((i) => introAt === undefined || i < introAt)

  const taken = new Set<number>() // 표제·초록·참고문헌으로 뺀 블록의 자리
  const front: string[] = []
  const abstract: Piece[] = []
  let guessed = false
  let absIdx: number | undefined
  let next = 0 // 초록 다음 블록 자리(Keywords 를 찾을 곳)

  const labeled = beforeIntro.find((i) => ABSTRACT_RE.test(en(blocks[i])))
  if (labeled !== undefined) {
    // ① 이름표가 붙은 초록
    absIdx = labeled
    const b = blocks[labeled]
    const rest = en(b).replace(ABSTRACT_RE, '')
    next = labeled + 1
    if (rest.length >= 20) {
      abstract.push({ key: `a${b.order}`, en: rest, ko: (b.text_ko || '').replace(ABSTRACT_RE, '') })
    } else {
      // "Abstract" 가 제목 한 줄로 따로 떨어진 논문 — 다음 소제목·서론 전까지를 초록으로 본다
      let total = 0
      for (let n = 0; next < blocks.length && n < 4 && total < 1000; next++) {
        const c = blocks[next]
        if (!isText(c)) continue
        if (isHeading(c) || KEYWORDS_RE.test(en(c)) || INTRO_RE.test(en(c))) break
        abstract.push({ key: `a${c.order}`, en: en(c), ko: c.text_ko || '' })
        taken.add(next)
        total += en(c).length
        n++
      }
    }
  } else {
    const inline = beforeIntro.find((i) => {
      const m = ABSTRACT_INLINE_RE.exec(en(blocks[i]))
      return !!m && en(blocks[i]).length - (m.index + m[0].length) >= 300
    })
    if (inline !== undefined) {
      // ② 제목·저자와 한 덩어리로 뽑힌 초록 — "Abstract" 낱말에서 둘로 가른다
      absIdx = inline
      next = inline + 1
      const b = blocks[inline]
      const t = en(b)
      const m = ABSTRACT_INLINE_RE.exec(t)!
      const before = withoutTitle(t.slice(0, m.index), title)
      if (before) front.push(before)
      const k = b.text_ko || ''
      const km = /\babstract\b[\s:.\-–—]*|초록[\s:.\-–—]*/i.exec(k)
      abstract.push({ key: `a${b.order}`, en: t.slice(m.index + m[0].length), ko: km ? k.slice(km.index + km[0].length) : k })
    } else {
      // ③ 표시가 없는 논문 — 첫 두 쪽에서 서론 앞의 **첫 긴 글** 이 줄글 문단일 때만 초록으로 추정한다.
      //    첫 긴 글이 줄글이 아니면(저자 목록·면책 문구 등) 그 뒤를 더 뒤지지 않는다 — 본문 문단을 초록이라 부르게 된다.
      const head3 = squash(title).toLowerCase()
      const g = beforeIntro.find((i) => blocks[i].page <= 2 && en(blocks[i]).length >= 450)
      const gt = g === undefined ? '' : squash(en(blocks[g]))
      if (g === undefined || !looksLikeProse(gt) || (head3 && gt.toLowerCase().startsWith(head3))) return none
      absIdx = g
      next = g + 1
      guessed = true
      abstract.push({ key: `a${blocks[g].order}`, en: en(blocks[g]), ko: blocks[g].text_ko || '' })
    }
  }
  if (abstract.reduce((n, p) => n + p.en.length, 0) < 200) return none // 초록이라기엔 너무 짧다 → 나누지 않는다
  taken.add(absIdx)

  // 표제: 초록 앞의 글
  const lead: string[] = []
  for (let i = 0; i < absIdx; i++) {
    if (!isText(blocks[i])) continue
    const t = withoutTitle(en(blocks[i]), title)
    if (t) lead.push(t)
    taken.add(i)
  }
  front.unshift(...lead)

  // 초록 바로 뒤의 Keywords 한 줄은 초록 상자에 같이 넣는다
  while (next < blocks.length && !isText(blocks[next])) next++
  if (next < blocks.length && !taken.has(next) && KEYWORDS_RE.test(en(blocks[next]))) {
    const c = blocks[next]
    abstract.push({ key: `a${c.order}`, en: en(c), ko: c.text_ko || '' })
    taken.add(next)
  }

  // 참고문헌: 뒤쪽 절반에서 마지막으로 "REFERENCES" 로 시작하는 글부터, 그림이 다시 나오기 전까지
  const refs: Block[] = []
  let refIdx = -1
  for (let i = blocks.length - 1; i >= Math.floor(blocks.length / 2); i--) {
    if (isText(blocks[i]) && REFS_RE.test(en(blocks[i]))) {
      refIdx = i
      break
    }
  }
  if (refIdx > absIdx) {
    for (let i = refIdx; i < blocks.length && isText(blocks[i]); i++) {
      refs.push(blocks[i])
      taken.add(i)
    }
  }

  return { front, abstract, guessed, body: blocks.filter((_, i) => !taken.has(i)), refs, split: true }
}

// 글자 크기 — 브라우저 확대를 건드리지 않고 본문만 조절한다.
// 최소 5 / 기본 10 (호야 지시 2026-07-28: 이전 하한 13이 너무 커서 못 줄였다).
// 값을 저장할 때 **인덱스가 아니라 크기 자체**를 넣는다 — 배열이 바뀌면 인덱스는
// 엉뚱한 크기를 가리키기 때문(이번 변경으로 실제로 어긋났다).
const SIZES = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14.5, 16, 18, 20, 22, 24] as const
const DEFAULT_SIZE = 10
const SIZE_KEY = 'reader_font_pt'
const TONE_KEY = 'reader_tone'
type Tone = 'light' | 'dark'

export function ReaderView() {
  const translateOne = useTranslateOne()
  const { readerOpen, closeReader, selectedId, documents, openChat, health } = useApp()
  const [blocks, setBlocks] = useState<Block[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [lang, setLang] = useState<Lang>('ko')
  const [sizeIdx, setSizeIdx] = useState<number>(() => {
    const saved = Number(localStorage.getItem(SIZE_KEY))
    const i = SIZES.indexOf(saved as (typeof SIZES)[number])
    return i >= 0 ? i : SIZES.indexOf(DEFAULT_SIZE)
  })

  const setSize = (i: number) => {
    const clamped = Math.max(0, Math.min(SIZES.length - 1, i))
    setSizeIdx(clamped)
    localStorage.setItem(SIZE_KEY, String(SIZES[clamped]))
  }
  const fontSize = SIZES[sizeIdx]

  const [tone, setToneState] = useState<Tone>(() =>
    localStorage.getItem(TONE_KEY) === 'dark' ? 'dark' : 'light',
  )
  const setTone = (t: Tone) => {
    setToneState(t)
    localStorage.setItem(TONE_KEY, t)
  }

  // 읽은 만큼 차오르는 선 — 스크롤하는 것은 Drawer 의 body 라서 거기에 귀를 건다
  const articleRef = useRef<HTMLElement>(null)
  const [progress, setProgress] = useState(0)

  const doc = documents.find((d) => d.doc_id === selectedId)

  // 번역이 진행되면(번역된 블록 수가 바뀌면) 본문을 조용히 다시 읽어 온다 — 읽던 자리는 그대로 둔다.
  const translatedCount = doc?.translated_blocks ?? 0
  const loadedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!readerOpen || !selectedId) return
    let alive = true
    useApp.getState().refreshHealth() // 잠금 안내가 지금 상태와 어긋나지 않게
    const first = loadedFor.current !== selectedId
    if (first) {
      setBlocks(null)
      setLoading(true)
    }
    api
      .getBlocks(selectedId)
      .then((r) => {
        if (!alive) return
        setBlocks(r.blocks)
        loadedFor.current = selectedId
      })
      .catch(() => alive && first && setBlocks(null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [readerOpen, selectedId, translatedCount])

  const hasKo = !!blocks?.some((b) => b.text_ko)
  const sections = useMemo(() => splitSections(blocks ?? [], doc?.title ?? ''), [blocks, doc?.title])
  // 저자·소속이 길면(저널 안내문·저작권 문구까지 딸려 온 논문) 몇 줄만 보이고 접는다
  const [frontOpen, setFrontOpen] = useState(false)
  useEffect(() => setFrontOpen(false), [selectedId])
  const frontLong = sections.front.join(' ').length > 600

  useEffect(() => {
    const scroller = articleRef.current?.closest('.ant-drawer-body') as HTMLElement | null
    if (!scroller) return
    const onScroll = () => {
      const max = scroller.scrollHeight - scroller.clientHeight
      setProgress(max > 0 ? Math.min(1, scroller.scrollTop / max) : 0)
    }
    onScroll()
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [blocks, loading, readerOpen])

  const translating = doc?.status === 'translating'
  const locked = health ? !health.paid_apis_enabled : false
  // 번역이 중간에 멈춘 논문 — 남은 문단은 원문으로 보인다. 왜 멈췄는지(doc.error)와 이어서 하는 길을 알린다.
  const partial = !translating && !!doc?.translated && !doc.translate_complete
  const showNotice = translating || !hasKo || partial || !!doc?.error

  /** 본문 블록 하나 */
  const renderBlock = (b: Block): ReactNode => {
    // ── 그림 / 표: 원본 그대로, 캡션은 아래
    if (b.kind === 'image' || b.kind === 'table') {
      const capText = lang === 'en' ? b.text_en : b.text_ko || b.text_en
      const capAlt = (b.text_ko || b.text_en || `p.${b.page}`).replace(/\s+/g, ' ')
      // 「나란히」에서는 캡션도 두 언어로 — 예전에는 한국어만 나와 원문 캡션을 대조할 수 없었다(점검 2026-10-14)
      const capBoth = lang === 'both' && !!b.text_ko && !!b.text_en && b.text_ko !== b.text_en
      return (
        <figure key={b.order}>
          {b.image_url && <img src={b.image_url} alt={capAlt} />}
          {capText && <figcaption>{lang === 'en' ? capText : ko(capText)}</figcaption>}
          {capBoth && <figcaption className="rd-cap-en">{b.text_en}</figcaption>}
          {b.analysis_ko && lang !== 'en' && (
            <div
              className="ai-response"
              style={{
                marginTop: '0.8em',
                fontSize: '0.92em',
                lineHeight: 1.85,
                whiteSpace: 'pre-wrap',
                textAlign: 'left',
              }}
            >
              <div className="ai-label">✦ AI FIGURE ANALYSIS</div>
              {ko(b.analysis_ko)}
            </div>
          )}
          {b.kind === 'table' && b.table_rows && b.table_rows.length > 1 && (
            <Table
              size="small"
              pagination={false}
              scroll={{ x: true }}
              style={{ marginTop: 12 }}
              dataSource={b.table_rows.slice(1).map((r, i) => ({ key: i, ...r }))}
              columns={b.table_rows[0].map((h, i) => ({
                title: h || `열${i + 1}`,
                dataIndex: i,
                ellipsis: true,
              }))}
            />
          )}
        </figure>
      )
    }

    // 캡션 텍스트는 그림에 이미 붙였으므로 본문에서 생략.
    // 단, 어느 그림에도 붙지 못한 캡션(attached === false)은 숨기면 내용이 사라진다 → 아래에서 글로 보여 준다.
    // (표를 그림으로 못 뽑은 "Table 1 …" 이나, "Fig. 3 shows …" 로 시작해 캡션으로 오인된 본문 문장)
    if (b.is_caption && b.attached !== false) return null

    const enText = b.text_en || ''
    const koNode = ko(b.text_ko || enText) // 번역 없으면 원문에라도 gloss

    if (isHeading(b)) {
      const both = lang === 'both' && !!b.text_ko && b.text_ko !== enText
      return (
        <h2 key={b.order}>
          {lang === 'en' ? enText : koNode}
          {both && <span className="rd-h-en">{enText}</span>}
        </h2>
      )
    }

    // 번역이 없는 문단은 「나란히」에서 같은 글이 두 번 나왔다 → 한 번만
    if (lang === 'both' && b.text_ko && b.text_ko !== enText) {
      return (
        <div key={b.order} style={{ marginBottom: 24 }}>
          <p style={{ margin: 0 }}>{koNode}</p>
          <p className="rd-en">{enText}</p>
        </div>
      )
    }
    if (lang === 'both') return <p key={b.order}>{enText}</p>
    return <p key={b.order}>{lang === 'en' ? enText : koNode}</p>
  }

  /** 초록 문단 */
  const renderAbstract = (p: Piece): ReactNode => {
    // 번역이 없는 초록은 「나란히」에서 같은 글이 두 번 나왔다 → 한 번만(2차 감독 점검: 7편)
    if (lang === 'both' && (!p.ko || p.ko === p.en)) return <p key={p.key}>{p.en}</p>
    if (lang === 'both') {
      return (
        <div key={p.key} style={{ marginBottom: '1em' }}>
          <p style={{ margin: 0 }}>{ko(p.ko || p.en)}</p>
          <p className="rd-en">{p.en}</p>
        </div>
      )
    }
    return <p key={p.key}>{lang === 'en' ? p.en : ko(p.ko || p.en)}</p>
  }

  return (
    <Drawer
      open={readerOpen}
      onClose={closeReader}
      width="min(1040px, 100vw)"
      rootClassName={`pa-reader${tone === 'dark' ? ' dark' : ''}`}
      title={
        <div className="pa-reader-title">
          <span className="t" title={doc?.title}>
            {doc?.title ?? '논문'}
          </span>
          {!!doc?.page_count && <span className="pg">{doc.page_count}p</span>}
        </div>
      }
    >
      {loading && <Spin style={{ display: 'block', margin: '100px auto' }} />}
      {!loading && !blocks?.length && <Empty description="내용이 없습니다" />}

      {!loading && !!blocks?.length && (
        <>
        <div className="pa-progress">
          <i style={{ width: `${progress * 100}%` }} />
        </div>
        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
          {/* 좌측 세로 도구 막대 — 제목 길이와 무관하게 항상 보인다.
              (헤더에 두면 긴 제목이 화면 밖으로 밀어냈다 — 실측 문제) */}
          <div className="pa-tool">
            <div className="lbl">보기</div>
            {(
              [
                ['ko', '한국어'],
                ['en', '원문'],
                ['both', '나란히'],
              ] as [Lang, string][]
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                className={`pa-tbtn${lang === v ? ' active' : ''}`}
                onClick={() => setLang(v)}
              >
                {label}
              </button>
            ))}

            <div className="lbl">글자 {fontSize}</div>
            <div className="row">
              <button
                type="button"
                className="pa-tbtn"
                disabled={sizeIdx === 0}
                onClick={() => setSize(sizeIdx - 1)}
                title="글자 작게"
              >
                A−
              </button>
              <button
                type="button"
                className="pa-tbtn"
                disabled={sizeIdx === SIZES.length - 1}
                onClick={() => setSize(sizeIdx + 1)}
                title="글자 크게"
              >
                A+
              </button>
            </div>

            <div className="lbl">배경</div>
            <div className="row">
              <button
                type="button"
                className={`pa-swatch light${tone === 'light' ? ' active' : ''}`}
                onClick={() => setTone('light')}
                title="밝게"
                aria-label="배경 밝게"
              />
              <button
                type="button"
                className={`pa-swatch night${tone === 'dark' ? ' active' : ''}`}
                onClick={() => setTone('dark')}
                title="어둡게"
                aria-label="배경 어둡게"
              />
            </div>

            {/* 원문을 읽다가 바로 물어볼 수 있게 — 라이브러리와 같은 좌측 챗봇 패널을 연다 */}
            <button type="button" className="ask" onClick={openChat} title="AI챗봇 (질문&요약)">
              <MessageOutlined />
              AI챗봇
            </button>
          </div>

          <article
            ref={articleRef}
            className="reader-body"
            style={{ flex: 1, minWidth: 0, fontSize, ['--reader-fs' as string]: `${fontSize}px` }}
          >
            {/* 번역 상태를 사실대로 알린다 — 진행 중인지, 잠금 때문인지, 중간에 멈췄는지(왜 멈췄는지까지) */}
            {showNotice && (
              <div className={`rd-notice${translating ? ' busy' : ''}`}>
                <div className="ico">{translating || !doc?.error ? <TranslationOutlined /> : <WarningOutlined />}</div>
                <div className="txt">
                  {translating ? (
                    <>
                      <b>번역하는 중입니다</b>
                      <span>
                        {doc?.translated_blocks ?? 0} / {doc?.text_blocks ?? '…'} 문단 · 끝난 부분부터 한국어로
                        바뀝니다
                      </span>
                      <Progress
                        percent={doc?.progress ?? 0}
                        size="small"
                        showInfo={false}
                        strokeColor={{ from: '#8b5cf6', to: '#6366f1' }}
                        style={{ margin: '6px 0 0' }}
                      />
                    </>
                  ) : partial ? (
                    <>
                      <b>번역이 일부만 끝났습니다</b>
                      <span>
                        {doc?.translated_blocks ?? 0} / {doc?.text_blocks ?? '…'} 문단 · 남은 문단은 원문으로
                        보입니다.
                        {locked &&
                          (health?.offline_mode
                            ? ' 완전 로컬 모드라 이어서 번역할 수 없습니다.'
                            : ' 이어서 번역하려면 유료 API 잠금을 먼저 풀어야 합니다.')}
                      </span>
                    </>
                  ) : hasKo ? (
                    <b>처리하다 남은 알림이 있습니다</b>
                  ) : locked ? (
                    <>
                      <b>아직 번역하지 않은 논문입니다</b>
                      <span>
                        {health?.offline_mode
                          ? '완전 로컬 모드라 번역을 실행할 수 없습니다. 원문은 그대로 읽을 수 있습니다.'
                          : '지금은 유료 API가 잠겨 있습니다. 위 메뉴바의 잠금 배지를 눌러 켜면 번역할 수 있습니다.'}
                      </span>
                    </>
                  ) : (
                    <>
                      <b>아직 번역하지 않은 논문입니다</b>
                      <span>
                        번역은 논문마다 한 번 실행합니다(유료). 원문은 지금도 그대로 읽을 수 있습니다.
                      </span>
                    </>
                  )}
                  {!translating && doc?.error && <span className="why">사유: {doc.error}</span>}
                </div>
                {!translating && !locked && doc?.status === 'ready' && (!hasKo || partial) && (
                  <button
                    type="button"
                    className="go"
                    disabled={translateOne.starting}
                    onClick={() => doc && translateOne.start(doc)}
                  >
                    {partial ? '이어서 번역' : '지금 번역'}
                  </button>
                )}
              </div>
            )}

            {sections.split && (
              <>
                {/* ── 표제: 제목 + 저자·소속 ── */}
                <header className="rd-front">
                  <div className="rd-kicker">논문{doc?.page_count ? ` · ${doc.page_count}쪽` : ''}</div>
                  <h1>{doc?.title}</h1>
                  {sections.front.length > 0 && (
                    <div className={`rd-metas${frontLong && !frontOpen ? ' clamp' : ''}`}>
                      {sections.front.map((t, i) => (
                        <p key={i} className="rd-meta">
                          {t}
                        </p>
                      ))}
                    </div>
                  )}
                  {frontLong && (
                    <button type="button" className="rd-more" onClick={() => setFrontOpen(!frontOpen)}>
                      {frontOpen ? '접기' : '저자·소속 전체 보기'}
                    </button>
                  )}
                </header>

                {/* ── 초록 ── */}
                <section className="rd-abstract">
                  <div className="rd-label">
                    {sections.guessed ? '초록 (추정) · 서론 앞 첫 문단' : 'ABSTRACT · 초록'}
                  </div>
                  {sections.abstract.map(renderAbstract)}
                </section>

                <div className="rd-divider">
                  <span>본문</span>
                </div>
              </>
            )}

            {!sections.split && doc?.title && (
              <header className="rd-front">
                <div className="rd-kicker">논문{doc.page_count ? ` · ${doc.page_count}쪽` : ''}</div>
                <h1 style={{ marginBottom: 0 }}>{doc.title}</h1>
              </header>
            )}

            {/* 큰 제목으로 이미 보여 준 제목 줄은 본문에서 되풀이하지 않는다 */}
            {sections.body
              .filter((b) => !(isText(b) && squash(en(b)).toLowerCase() === squash(doc?.title ?? '').toLowerCase()))
              .map(renderBlock)}

            {/* ── 참고문헌: 번역 대상이 아니라 원문 그대로, 작고 옅게 ── */}
            {sections.refs.length > 0 && (
              <section className="rd-refs">
                <div className="rd-label">REFERENCES · 참고문헌</div>
                {sections.refs.map((b, i) => (
                  <p key={b.order}>{i === 0 ? (b.text_en || '').replace(REFS_RE, '') : b.text_en}</p>
                ))}
              </section>
            )}

            <div className="rd-end">— END —</div>
          </article>
        </div>
        </>
      )}
    </Drawer>
  )
}
