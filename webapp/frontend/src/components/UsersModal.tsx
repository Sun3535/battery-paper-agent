// 사용자별 API 키 관리 모달.
//
// 흐름 (호야 지시):
//   - 평소에는 **사용자명만** 보인다.
//   - 이름 클릭 → 비밀번호 팝업(도용 방지) → 통과 시 그 사용자의 키를 "활성"으로 지정
//     → 이후 번역은 이 사용자의 API 키를 쓴다.
//   - 이름 옆 [API] 버튼 → 비밀번호 입력 → 맞으면 API 키 입력/수정란이 뜬다.
//   - [+ 추가] 로 사용자 생성(이름·비번·키), [삭제]는 비밀번호 확인 후.
//
// 보안: 목록 API는 이름만 내려준다. 비번·키는 비밀번호가 맞을 때만 서버가 반환한다.

import { DeleteOutlined, KeyOutlined, PlusOutlined, UserOutlined } from '@ant-design/icons'
import { App, Button, Input, Modal, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { api, type UserRow } from '../api'
import { T } from '../theme'
import { CredentialPanel } from './CredentialPanel'

type Panel =
  | { kind: 'none' }
  | { kind: 'key'; username: string; step: 'pw' | 'edit'; password: string; apiKey: string }
  | { kind: 'activate'; username: string; password: string }
  | { kind: 'delete'; username: string; password: string }
  | { kind: 'add'; username: string; password: string; apiKey: string }

export function UsersModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<UserRow[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [panel, setPanel] = useState<Panel>({ kind: 'none' })
  const [busy, setBusy] = useState(false)

  const refresh = () =>
    api.listUsers().then((d) => {
      setRows(d.users)
      setActive(d.active)
    })

  useEffect(() => {
    if (open) {
      refresh()
      setPanel({ kind: 'none' })
    }
  }, [open])

  const err = (e: unknown) => message.error((e as Error).message)

  // ── 액션들 ──────────────────────────────
  const doAdd = async (p: Extract<Panel, { kind: 'add' }>) => {
    if (!p.username.trim() || !p.password) return message.warning('사용자명과 비밀번호는 필수입니다.')
    setBusy(true)
    try {
      await api.addUser(p.username.trim(), p.password, p.apiKey.trim())
      message.success('사용자를 추가했습니다.')
      setPanel({ kind: 'none' })
      await refresh()
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  // 키 조회/저장은 CredentialPanel(3종 슬롯)이 직접 처리한다.

  const doActivate = async (username: string, password: string) => {
    setBusy(true)
    try {
      await api.activateUser(username, password)
      message.success(`'${username}' 사용자로 활성화했습니다. 이제 이 사용자의 API 키로 번역합니다.`)
      setPanel({ kind: 'none' })
      await refresh()
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  const doDelete = async (username: string, password: string) => {
    setBusy(true)
    try {
      await api.deleteUser(username, password)
      message.success('삭제했습니다.')
      setPanel({ kind: 'none' })
      await refresh()
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  const deactivate = async () => {
    await api.deactivate()
    await refresh()
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="사용자 · API 키"
      width={460}
    >
      <div style={{ fontSize: 12, color: T.textFaint, marginBottom: 14, lineHeight: 1.6 }}>
        이름을 클릭하면 비밀번호 확인 후 그 사용자의 API 키로 번역합니다. [API] 버튼으로 키를
        등록·수정할 수 있어요.
      </div>

      {/* 현재 활성 사용자 */}
      <div style={{ marginBottom: 12 }}>
        {active ? (
          <Tag color="success">
            현재 번역 사용자: {active}
            <a style={{ marginLeft: 8, color: T.textFaint }} onClick={deactivate}>
              해제
            </a>
          </Tag>
        ) : (
          <Tag color="default">활성 사용자 없음 (번역 시 .env 키 사용)</Tag>
        )}
      </div>

      {/* 사용자 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((u) => (
          <div
            key={u.username}
            style={{
              border: `1px solid ${active === u.username ? T.primary : T.border}`,
              borderRadius: T.radiusMd,
              padding: '8px 10px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <UserOutlined style={{ color: T.textFaint }} />
              <a
                style={{ flex: 1, color: T.text, fontWeight: 500 }}
                onClick={() => setPanel({ kind: 'activate', username: u.username, password: '' })}
              >
                {u.username}
              </a>
              {!u.has_key && <Tag style={{ fontSize: 10 }}>키 없음</Tag>}
              <Button
                size="small"
                icon={<KeyOutlined />}
                onClick={() =>
                  setPanel({ kind: 'key', username: u.username, step: 'pw', password: '', apiKey: '' })
                }
              >
                API
              </Button>
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => setPanel({ kind: 'delete', username: u.username, password: '' })}
              />
            </div>

            {/* 자격증명 3종(무료키·유료키·크레딧) 관리 — [API] 버튼으로 열고 닫는다 */}
            {panel.kind === 'key' && panel.username === u.username && (
              <CredentialPanel username={u.username} />
            )}

            {panel.kind === 'activate' && panel.username === u.username && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${T.border}` }}>
                <PwRow
                  label={`'${u.username}'의 비밀번호 (도용 방지)`}
                  value={panel.password}
                  onChange={(v) => setPanel({ ...panel, password: v })}
                  onSubmit={() => doActivate(u.username, panel.password)}
                  busy={busy}
                  submitText="이 사용자로 번역"
                />
              </div>
            )}

            {panel.kind === 'delete' && panel.username === u.username && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${T.border}` }}>
                <PwRow
                  label={`삭제하려면 '${u.username}'의 비밀번호 입력`}
                  value={panel.password}
                  onChange={(v) => setPanel({ ...panel, password: v })}
                  onSubmit={() => doDelete(u.username, panel.password)}
                  busy={busy}
                  submitText="삭제"
                  danger
                />
              </div>
            )}
          </div>
        ))}
        {!rows.length && (
          <div style={{ color: T.textFaint, fontSize: 13, textAlign: 'center', padding: '16px 0' }}>
            등록된 사용자가 없습니다. 아래 + 로 추가하세요.
          </div>
        )}
      </div>

      {/* 추가 */}
      {panel.kind === 'add' ? (
        <div
          style={{
            marginTop: 12,
            border: `1px solid ${T.primary}`,
            borderRadius: T.radiusMd,
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div style={{ fontWeight: 500, fontSize: 13 }}>새 사용자</div>
          <Input
            placeholder="사용자명"
            value={panel.username}
            onChange={(e) => setPanel({ ...panel, username: e.target.value })}
          />
          <Input.Password
            placeholder="비밀번호"
            value={panel.password}
            onChange={(e) => setPanel({ ...panel, password: e.target.value })}
          />
          <Input.Password
            placeholder="Gemini API 키 (선택 — 나중에 [API] 버튼에서 등록해도 됩니다)"
            value={panel.apiKey}
            onChange={(e) => setPanel({ ...panel, apiKey: e.target.value })}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Button type="primary" size="small" loading={busy} onClick={() => doAdd(panel)}>
              추가
            </Button>
            <Button size="small" onClick={() => setPanel({ kind: 'none' })}>
              취소
            </Button>
          </div>
        </div>
      ) : (
        <Button
          block
          icon={<PlusOutlined />}
          style={{ marginTop: 12 }}
          onClick={() => setPanel({ kind: 'add', username: '', password: '', apiKey: '' })}
        >
          사용자 추가
        </Button>
      )}

      <div style={{ fontSize: 11, color: T.textFaint, marginTop: 14, lineHeight: 1.6 }}>
        ⚠️ 비밀번호·API 키는 로컬 DB에 평문 저장됩니다(localhost 전용). 중요한 서비스의 비밀번호를
        재사용하지 마세요.
      </div>
    </Modal>
  )
}

function PwRow(props: {
  label: string
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
  submitText: string
  danger?: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 12, color: T.textDim }}>{props.label}</div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Input.Password
          autoFocus
          placeholder="비밀번호"
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          onPressEnter={props.onSubmit}
        />
        <Button
          type="primary"
          danger={props.danger}
          size="middle"
          loading={props.busy}
          onClick={props.onSubmit}
        >
          {props.submitText}
        </Button>
      </div>
    </div>
  )
}
