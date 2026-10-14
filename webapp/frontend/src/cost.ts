// 번역 비용 어림값 — 버튼·확인창이 같은 계산을 쓴다.
//
// 어림값은 서버(/api/health 의 translate_cost)가 공급자·모델에 맞춰 알려 준다:
//   Gemini = 편당, Claude = 쪽당. 서버가 옛 버전이라 값이 없으면 기존 어림값(편당 ₩121)을 쓴다.

import type { DocumentMeta, Health } from './api'

const FALLBACK_PER_PAPER = 121

export function translateEstimate(
  health: Health | null,
  docs: Pick<DocumentMeta, 'page_count'>[],
): { krw: number; basis: string } {
  const c = health?.translate_cost
  if (c?.per_page_krw) {
    const pages = docs.reduce((n, d) => n + (d.page_count || 0), 0)
    return { krw: pages * c.per_page_krw, basis: `쪽당 ~₩${c.per_page_krw} · ${pages}쪽` }
  }
  const per = c?.per_paper_krw ?? FALLBACK_PER_PAPER
  return { krw: docs.length * per, basis: `편당 ~₩${per}` }
}

/** 버튼 옆에 붙이는 짧은 단가 표시 */
export function translateUnitLabel(health: Health | null): string {
  const c = health?.translate_cost
  if (c?.per_page_krw) return `~₩${c.per_page_krw}/쪽`
  return `~₩${c?.per_paper_krw ?? FALLBACK_PER_PAPER}/편`
}
