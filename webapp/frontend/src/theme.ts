// 디자인 토큰 — "Paper Agent Violet" (2026-10-13).
// 공정 플랫폼(파랑)·분석 플랫폼(초록)과 같은 가족 디자인의 **보라** 판이다.
//   밝은 바탕 + 위쪽의 은은한 보라 빛 / 떠 있는 유리 메뉴바 / 그림자로 입체감을 준 흰 카드.
// Stitch 프로젝트 "Paper E-book Reader Redesign (Light · Violet)" 에서 옮겼다.
// 색·간격·라운드는 전부 여기서만 관리한다(컴포넌트에 하드코딩 금지).
// 색은 `${color}55` 처럼 투명도를 덧붙여 쓰는 곳이 있어 **6자리 hex 로만** 적는다.

import type { ThemeConfig } from 'antd'
import { theme as antdTheme } from 'antd'

export const T = {
  bg: '#F7F6FD', // 앱 바탕 — 완전 흰색이 아니다(보라 기운)
  panel: '#FFFFFF', // 카드·패널 표면
  hover: '#F5F3FF', // 활성/호버 (옅은 보라)
  float: '#FFFFFF', // 팝오버·모달

  border: '#E9E5F5',
  borderStrong: '#CFC8EA',

  primary: '#7C3AED', // Violet — 주 액션·선택 상태
  primaryDeep: '#6D28D9',
  ai: '#4F46E5', // Indigo — AI 생성물 전용
  success: '#059669', // Emerald — 검증됨/완료
  warning: '#B45309', // Amber — 비용·잠금 안내
  danger: '#DC2626',

  text: '#1B1730',
  textDim: '#55506B',
  textFaint: '#8E89A6',

  radiusSm: 10, // 버튼·인풋·태그
  radiusMd: 16, // 카드·AI 요소

  readerWidth: 800, // 리더 본문 최적 줄길이
  font: "'Pretendard Variable', Pretendard, 'Inter', -apple-system, 'Malgun Gothic', sans-serif",
} as const

export const antdConfig: ThemeConfig = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: T.primary,
    colorInfo: T.primary,
    colorLink: T.primary,
    colorBgBase: '#FFFFFF',
    colorBgLayout: T.bg,
    colorBgContainer: T.panel,
    colorBgElevated: T.float,
    colorBorder: T.border,
    colorBorderSecondary: T.border,
    colorText: T.text,
    colorTextSecondary: T.textDim,
    colorTextTertiary: T.textFaint,
    colorSuccess: T.success,
    colorWarning: T.warning,
    colorError: T.danger,
    borderRadius: T.radiusSm,
    borderRadiusLG: T.radiusMd,
    borderRadiusSM: 8,
    fontFamily: T.font,
    fontSize: 14,
    controlHeight: 36,
  },
  components: {
    Tabs: { itemColor: T.textFaint, itemSelectedColor: T.text, itemHoverColor: T.text },
    Drawer: { colorBgElevated: T.panel },
    Modal: { borderRadiusLG: 22 },
    Button: { fontWeight: 500, primaryShadow: 'none', defaultShadow: 'none' },
    Segmented: { trackBg: '#F1EEFA', itemSelectedBg: '#FFFFFF' },
  },
}
