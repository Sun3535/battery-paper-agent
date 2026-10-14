// 챗봇 대화 기억 (맞춤형 스킬) 관리.
//
// 켜면: 새 질문이 올 때 관련된 과거 Q&A 2~3개를 챗봇에게 함께 준다 → 일관된 답, 오답 감소.
// 비용: 저장·검색은 로컬(0원). 크레딧은 "주입되는 입력 토큰"만 추가되며, 관련 기억이 없으면 0.
// 그래서 스위치로 언제든 끌 수 있게 했다.

import { DeleteOutlined } from '@ant-design/icons'
import { App, Button, Empty, Modal, Popconfirm, Switch, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { api, type MemoryItem } from '../api'
import { T } from '../theme'

export function MemoryModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const [enabled, setEnabled] = useState(false)
  const [rows, setRows] = useState<Required<MemoryItem>[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = () =>
    api.listMemory().then((d) => {
      setEnabled(d.enabled)
      setRows(d.memories)
    })

  useEffect(() => {
    if (open) refresh().catch(() => {})
  }, [open])

  const toggle = async (on: boolean) => {
    setBusy(true)
    try {
      await api.toggleMemory(on)
      setEnabled(on)
      message.success(on ? '기억 사용 ON — 관련 대화를 참고해 답합니다.' : '기억 사용 OFF — 추가 비용 0.')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="챗봇 대화 기억 (맞춤형 스킬)" width={520}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '10px 12px',
          border: `1px solid ${enabled ? T.primary : T.border}`,
          borderRadius: T.radiusMd,
          marginBottom: 14,
        }}
      >
        <Switch checked={enabled} loading={busy} onChange={toggle} />
        <div style={{ flex: 1, fontSize: 12, lineHeight: 1.6, color: T.textDim }}>
          <div style={{ color: T.text, fontWeight: 500 }}>
            {enabled ? '기억 사용 중' : '기억 사용 안 함 (기본)'}
          </div>
          질문할 때 관련된 과거 Q&A {rows.length ? '' : ''}를 챗봇에게 함께 전달해 일관된 답을 유도합니다.
        </div>
      </div>

      <div style={{ fontSize: 11, color: T.textFaint, lineHeight: 1.7, marginBottom: 12 }}>
        💡 저장·검색은 <b style={{ color: T.success }}>전부 로컬(0원)</b>입니다. 크레딧은 관련 기억을
        프롬프트에 넣는 입력 토큰(회당 대략 70~100토큰)만 추가되고, 관련 기억이 없으면 0입니다.
        “정보 없음” 같은 답은 학습 가치가 없어 저장하지 않습니다.
      </div>

      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: T.textDim, flex: 1 }}>저장된 기억 {rows.length}건</span>
        {!!rows.length && (
          <Popconfirm
            title="모든 기억을 삭제할까요?"
            onConfirm={async () => {
              const r = await api.clearMemory()
              message.success(`${r.deleted}건 삭제`)
              refresh()
            }}
          >
            <Button size="small" danger>
              전체 삭제
            </Button>
          </Popconfirm>
        )}
      </div>

      <div style={{ maxHeight: 340, overflowY: 'auto' }}>
        {rows.map((m) => (
          <div
            key={m.id}
            style={{
              border: `1px solid ${T.border}`,
              borderRadius: T.radiusMd,
              padding: '8px 10px',
              marginBottom: 6,
            }}
          >
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: T.text, fontWeight: 500 }}>Q. {m.question}</div>
                <div style={{ fontSize: 12, color: T.textDim, marginTop: 4, lineHeight: 1.6 }}>
                  {m.answer_summary}
                </div>
                {m.doc_titles && (
                  <Tag style={{ fontSize: 10, marginTop: 6 }}>{m.doc_titles.slice(0, 40)}</Tag>
                )}
              </div>
              <Button
                size="small"
                type="text"
                icon={<DeleteOutlined />}
                onClick={async () => {
                  await api.deleteMemory(m.id)
                  refresh()
                }}
              />
            </div>
          </div>
        ))}
        {!rows.length && (
          <Empty
            description={
              <span style={{ fontSize: 12, color: T.textFaint }}>
                아직 저장된 기억이 없습니다.
                <br />
                기억을 켠 뒤 챗봇에 질문하면 쌓입니다.
              </span>
            }
          />
        )}
      </div>
    </Modal>
  )
}
