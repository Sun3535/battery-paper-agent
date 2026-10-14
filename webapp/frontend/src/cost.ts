// 번역 비용 어림값 — 버튼·확인창이 같은 계산을 쓴다.
//
// 어림값은 서버(/api/health 의 translate_cost)가 공급자·모델에 맞춰 알려 준다:
//   Gemini = 편당, Claude = 쪽당. 서버가 옛 버전이라 값이 없으면 기존 어림값(편당 ₩121)을 쓴다.

import type { DocumentMeta, Health } from './api'

const FALLBACK_PER_PAPER = 121

/** 아직 번역하지 않은 몫(0~1) — 일부만 번역된 논문을 이어서 할 때 남은 양만 셈한다 */
function remaining(d: Pick<DocumentMeta, 'translated_blocks' | 'text_blocks'>): number {
  const total = d.text_blocks ?? 0
  if (!total) return 1
  return Math.max(0, Math.min(1, 1 - (d.translated_blocks ?? 0) / total))
}

export function translateEstimate(
  health: Health | null,
  docs: Pick<DocumentMeta, 'page_count' | 'translated_blocks' | 'text_blocks'>[],
): { krw: number; basis: string } {
  const c = health?.translate_cost
  // 0 도 값이다(사내 API 가 무료) — 예전에는 0 을 '값 없음' 으로 읽어 편당 ₩121 로 보였다(2차 점검)
  if (c?.per_page_krw != null) {
    const pages = Math.round(docs.reduce((n, d) => n + (d.page_count || 0) * remaining(d), 0))
    const part = docs.some((d) => remaining(d) < 1) ? ' (남은 분량)' : ''
    return { krw: pages * c.per_page_krw, basis: `쪽당 ~₩${c.per_page_krw} · ${pages}쪽${part}` }
  }
  const per = c?.per_paper_krw ?? FALLBACK_PER_PAPER
  return { krw: docs.length * per, basis: `편당 ~₩${per}` }
}

/** 버튼 옆에 붙이는 짧은 단가 표시 */
export function translateUnitLabel(health: Health | null): string {
  const c = health?.translate_cost
  if (c?.per_page_krw != null) return `~₩${c.per_page_krw}/쪽`
  return `~₩${c?.per_paper_krw ?? FALLBACK_PER_PAPER}/편`
}
