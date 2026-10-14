// 영문 용어 → 한글 gloss 사전 (렌더링 시 ruby 주석으로 영문 아래에 회색 한글을 붙인다).
//
// 번역 파이프라인은 학술 용어를 영어로 남긴다(연구자 문체). 이 사전은 그 영어 용어 밑에
// 작은 회색 한글 뜻을 깔아 "한글 통일성"을 준다. 완전 로컬·무료 — API 호출 없음.
//
// 키는 소문자. 여러 단어/하이픈 용어도 됨(긴 것부터 매칭하므로 capacity retention이
// capacity보다 우선). 사전에 없는 영문(고유명사·화학식 Li7La3Zr2O12 등)은 gloss 없이 통과.

import type { ReactNode } from 'react'

export const GLOSSARY: Record<string, string> = {
  // ── 전지 구성 ──────────────────────────────
  cathode: '양극',
  anode: '음극',
  electrolyte: '전해질',
  electrode: '전극',
  separator: '분리막',
  'current collector': '집전체',
  'half-cell': '반쪽전지',
  'full-cell': '완전전지',
  'full cell': '완전전지',
  'coin cell': '코인셀',
  'pouch cell': '파우치셀',

  // ── 성능 지표 ──────────────────────────────
  'coulombic efficiency': '쿨롱 효율',
  'initial coulombic efficiency': '초기 쿨롱 효율',
  ice: '초기 쿨롱 효율',
  capacity: '용량',
  'specific capacity': '비용량',
  'areal capacity': '면적용량',
  'capacity retention': '용량 유지율',
  'cycle life': '수명',
  cyclability: '사이클 성능',
  'rate capability': '율속 특성',
  'energy density': '에너지 밀도',
  'power density': '출력 밀도',
  overpotential: '과전압',
  voltage: '전압',
  'voltage decay': '전압 감소',
  polarization: '분극',
  impedance: '임피던스',
  resistance: '저항',
  'interfacial resistance': '계면 저항',
  'ionic conductivity': '이온 전도도',
  conductivity: '전도도',
  diffusion: '확산',
  'diffusion coefficient': '확산 계수',

  // ── 소재 ───────────────────────────────────
  lithium: '리튬',
  sodium: '소듐',
  silicon: '실리콘',
  graphite: '흑연',
  'hard carbon': '하드카본',
  'lithium metal': '리튬 금속',
  'solid electrolyte': '고체 전해질',
  'solid-state': '전고체',
  'all-solid-state': '전고체',
  'li-ion': '리튬이온',
  'lithium-ion': '리튬이온',
  'sodium-ion': '소듐이온',
  'na-ion': '소듐이온',
  dendrite: '덴드라이트',
  sei: '고체전해질 계면막',
  'solid electrolyte interphase': '고체전해질 계면막',
  polysulfide: '폴리설파이드',
  nmc: '삼원계 양극재',
  ncm: '삼원계 양극재',
  lfp: '인산철리튬',
  lifepo4: '인산철리튬',
  'active material': '활물질',
  porosity: '기공도',
  pore: '기공',
  'closed pore': '닫힌 기공',
  'volume expansion': '부피 팽창',

  // ── 분석 기법 ──────────────────────────────
  xrd: 'X선 회절',
  sem: '주사전자현미경',
  tem: '투과전자현미경',
  xps: 'X선 광전자분광',
  raman: '라만 분광',
  eis: '임피던스 분광',
  dft: '밀도범함수이론',
  neb: '최소에너지경로',
  'cyclic voltammetry': '순환전압전류법',
  gcd: '정전류 충방전',

  // ── 반응·공정 ──────────────────────────────
  lithiation: '리튬 삽입',
  delithiation: '리튬 탈리',
  sodiation: '소듐 삽입',
  intercalation: '삽입',
  deintercalation: '탈리',
  charge: '충전',
  discharge: '방전',
  cycling: '사이클링',
  nucleation: '핵생성',
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// 긴 용어 우선(capacity retention > capacity). 단어 경계로 감싸 부분단어 오매칭 방지.
const PATTERN = new RegExp(
  '\\b(' +
    Object.keys(GLOSSARY)
      .sort((a, b) => b.length - a.length)
      .map(escapeRegex)
      .join('|') +
    ')\\b',
  'gi',
)

/** 텍스트에서 사전에 있는 영문 용어를 찾아 <ruby>영문<rt>한글</rt></ruby>로 감싼다.
 *  나머지는 원문 그대로. ruby-position:under (index.css)로 한글이 영문 아래에 깔린다. */
export function glossify(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  PATTERN.lastIndex = 0
  while ((m = PATTERN.exec(text)) !== null) {
    const term = m[0]
    const gloss = GLOSSARY[term.toLowerCase()]
    if (!gloss) continue
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(
      <ruby key={`${m.index}-${term}`}>
        {term}
        <rt>{gloss}</rt>
      </ruby>,
    )
    last = m.index + term.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
