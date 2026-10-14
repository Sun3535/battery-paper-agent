// 뼈대 — 떠 있는 유리 메뉴바 + 라이브러리 한 화면 (Stitch "Paper E-book Reader Redesign · Violet").
//   공정 플랫폼(파랑)·분석 플랫폼(초록)과 같은 가족 디자인이다.
// 화면은 라이브러리 하나뿐이다(호야 지시 2026-07-28). 그래서 메뉴바에 가짜 메뉴를 늘리지 않는다.
// AI 챗봇은 어디서든 좌측 패널로 열리고, 시각 자료는 리더 안에서 원래 자리로 본다.

import { BulbOutlined, MessageOutlined, ReadOutlined, UserOutlined } from '@ant-design/icons'
import { App as AntApp, ConfigProvider, Drawer, Tooltip } from 'antd'
import koKR from 'antd/locale/ko_KR'
import { useEffect, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { LibraryPathButton, LibraryPathModal } from './components/LibraryPathModal'
import { LibraryView } from './components/LibraryView'
import { MemoryModal } from './components/MemoryModal'
import { ReaderView } from './components/ReaderView'
import { UsersModal } from './components/UsersModal'
import { api } from './api'
import { useApp } from './store'
import { antdConfig } from './theme'

/** 비용 상태 배지 — 지금 돈이 나가는 구성인지 항상 보이게. **누르면 그 자리에서 잠근다.** */
function CostBadge() {
  const { message, modal } = AntApp.useApp()
  const refreshHealth = useApp((s) => s.refreshHealth)
  const [on, setOn] = useState<boolean | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => {
        setOn(!!d.paid_apis_enabled)
        setOffline(!!d.offline_mode)
      })
      .catch(() => setOn(null))
  }, [])

  const apply = async (next: boolean) => {
    try {
      const r = await api.togglePaid(next)
      setOn(r.paid_apis_enabled)
      refreshHealth() // 리더·버튼의 잠금 안내가 바로 따라오게
      ;(r.paid_apis_enabled ? message.warning : message.success)(r.message)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const click = () => {
    if (on === null) return
    // 끄는 건 언제나 안전 → 바로 실행. 켜는 건 과금이 시작되므로 한 번 확인받는다.
    if (on) return apply(false)
    modal.confirm({
      title: '유료 API를 다시 켤까요?',
      content: '켜는 순간부터 번역·그림분석·AI 요약에서 실제 과금이 발생합니다.',
      okText: '켜기',
      cancelText: '취소',
      onOk: () => apply(true),
    })
  }

  if (offline) {
    return (
      <span className="pa-cost offline" title="완전 로컬 모드 · 외부 통신 없음">
        📴 완전 로컬<span className="long"> 모드 · 외부 통신 없음</span>
      </span>
    )
  }
  if (on === null) return null

  return (
    <Tooltip title={on ? '클릭하면 유료 API를 잠급니다 (과금 즉시 중단)' : '클릭하면 다시 켤 수 있습니다'}>
      <span className={`pa-cost ${on ? 'live' : 'locked'}`} onClick={click} role="button">
        {on ? (
          <>
            <span className="dot" />
            유료 API 사용 중<span className="long"> — 눌러서 잠금</span>
          </>
        ) : (
          '🔒 유료 API 잠김'
        )}
      </span>
    </Tooltip>
  )
}

function MemoryButton({ onOpen }: { onOpen: () => void }) {
  const [on, setOn] = useState<boolean | null>(null)
  useEffect(() => {
    const load = () =>
      fetch('/api/health')
        .then((r) => r.json())
        .then((d) => setOn(!!d.memory_enabled))
        .catch(() => {})
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [])
  return (
    <button
      type="button"
      className={`pa-ghost hide-sm${on ? ' on' : ''}`}
      onClick={onOpen}
      title="챗봇 대화 기억 (맞춤형 스킬)"
    >
      <BulbOutlined />
      기억 {on === null ? '' : on ? 'ON' : 'OFF'}
      {on && <span className="dot" />}
    </button>
  )
}

function UserButton({ onOpen }: { onOpen: () => void }) {
  const [active, setActive] = useState<string | null>(null)
  useEffect(() => {
    const load = () =>
      fetch('/api/users')
        .then((r) => r.json())
        .then((d) => setActive(d.active))
        .catch(() => {})
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [])
  return (
    <button type="button" className="pa-ghost" onClick={onOpen} title="사용자 · API 키">
      <UserOutlined />
      <span className="lbl">{active ? active : '사용자'}</span>
    </button>
  )
}

function Shell() {
  const { refreshDocuments, refreshHealth, chatOpen, openChat, closeChat, checkedIds, documents, readerOpen } =
    useApp()
  const [usersOpen, setUsersOpen] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [pathOpen, setPathOpen] = useState(false)

  useEffect(() => {
    refreshHealth()
  }, [refreshHealth])

  useEffect(() => {
    refreshDocuments()
    const id = setInterval(() => {
      const busy = useApp
        .getState()
        .documents.some((d) => d.status !== 'ready' && d.status !== 'failed')
      if (busy) refreshDocuments()
    }, 3000)
    return () => clearInterval(id)
  }, [refreshDocuments])

  return (
    <div className="pa-app">
      <div className="pa-decor" />

      <header className="pa-nav">
        <div className="pa-brand">
          <div className="pa-brand-mark">
            <ReadOutlined />
          </div>
          <div className="pa-brand-name">
            논문<em>책방</em>
          </div>
        </div>
        <span className="pa-nav-tab">
          라이브러리
          <span className="count">{documents.length}</span>
        </span>

        <div className="pa-nav-actions">
          <CostBadge />
          <span className="pa-divider-v hide-sm" />
          <LibraryPathButton onOpen={() => setPathOpen(true)} />
          <MemoryButton onOpen={() => setMemoryOpen(true)} />
          <UserButton onOpen={() => setUsersOpen(true)} />
        </div>
      </header>

      <main className="pa-main">
        <LibraryView />
      </main>

      {/* 어느 화면에서든 바로 물어볼 수 있게 (Stitch의 "Ask anything") */}
      <button type="button" className="pa-pill-dark pa-fab" onClick={openChat}>
        <MessageOutlined />
        AI챗봇 (질문&요약)
      </button>

      {/* 챗봇은 **좌측**에서 열린다 — 원문(우측 리더)을 보면서 물어볼 수 있게. */}
      <Drawer
        open={chatOpen}
        onClose={closeChat}
        placement="left"
        width="min(560px, 100vw)"
        zIndex={1200}
        rootClassName="pa-chat-drawer"
        title={
          <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.02em' }}>
            AI챗봇 (질문&요약)
            {/* 논문을 읽는 중에는 챗봇이 '그 논문'에 묶인다 — 체크 개수 표시는 틀린 말이 되므로 숨긴다 */}
            {!!checkedIds.length && !readerOpen && (
              <span className="pa-chip" style={{ marginLeft: 8, color: '#6d28d9', background: '#ede9fe' }}>
                체크한 {checkedIds.length}편 집중
              </span>
            )}
          </span>
        }
      >
        <ChatPanel />
      </Drawer>

      <ReaderView />
      <UsersModal open={usersOpen} onClose={() => setUsersOpen(false)} />
      <MemoryModal open={memoryOpen} onClose={() => setMemoryOpen(false)} />
      <LibraryPathModal open={pathOpen} onClose={() => setPathOpen(false)} />
    </div>
  )
}

export default function App() {
  return (
    <ConfigProvider locale={koKR} theme={antdConfig}>
      <AntApp>
        <Shell />
      </AntApp>
    </ConfigProvider>
  )
}
