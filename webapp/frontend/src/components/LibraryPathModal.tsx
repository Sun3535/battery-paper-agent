// 논문 저장 폴더 변경 — 사용자마다 다른 라이브러리를 쓸 수 있게 한다.
//
// 폴더를 바꾸면 그 안에 {papers.db, uploads/, images/} 로 **독립된 라이브러리**가 만들어진다.
// 기존 데이터는 옮기지도 지우지도 않는다 — 경로만 전환된다(언제든 되돌릴 수 있다).

import { FolderOpenOutlined } from '@ant-design/icons'
import { App, Button, Input, Modal, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { api, type LibraryPaths } from '../api'
import { useApp } from '../store'
import { T } from '../theme'

export function LibraryPathModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message, modal } = App.useApp()
  const refreshDocuments = useApp((s) => s.refreshDocuments)
  const clearChecked = useApp((s) => s.clearChecked)
  const [info, setInfo] = useState<LibraryPaths | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    api
      .getLibraryPath()
      .then((d) => {
        setInfo(d)
        setPath(d.library_root ?? '')
      })
      .catch(() => {})
  }, [open])

  const apply = (target: string | null) => {
    modal.confirm({
      title: target ? '저장 폴더를 바꿀까요?' : '기본 폴더로 되돌릴까요?',
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ wordBreak: 'break-all', color: T.text }}>
            → <b>{target ?? '기본 위치(현재 앱 폴더 안)'}</b>
          </div>
          <div style={{ marginTop: 8, color: T.textDim }}>
            그 폴더의 라이브러리로 <b>전환</b>됩니다. 지금 논문들은 <b>지워지지 않고</b> 원래
            폴더에 그대로 남아 있으며, 경로를 되돌리면 다시 보입니다.
          </div>
        </div>
      ),
      okText: '변경',
      cancelText: '취소',
      onOk: async () => {
        setBusy(true)
        try {
          const d = await api.setLibraryPath(target)
          setInfo(d)
          setPath(d.library_root ?? '')
          clearChecked()
          await refreshDocuments()
          message.success(`저장 폴더를 바꿨습니다 — 논문 ${d.doc_count}편`)
        } catch (e) {
          message.error((e as Error).message)
        } finally {
          setBusy(false)
        }
      },
    })
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="논문 저장 폴더" width={520}>
      {info && (
        <>
          <div
            style={{
              border: `1px solid ${T.border}`,
              borderRadius: T.radiusMd,
              padding: '10px 12px',
              marginBottom: 14,
              fontSize: 12,
              lineHeight: 1.8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ color: T.textDim }}>현재 위치</span>
              <Tag color={info.is_default ? 'default' : 'processing'} style={{ margin: 0, fontSize: 10 }}>
                {info.is_default ? '기본' : '사용자 지정'}
              </Tag>
              <span style={{ marginLeft: 'auto', color: T.success }}>논문 {info.doc_count}편</span>
            </div>
            <div style={{ color: T.textFaint, wordBreak: 'break-all', fontSize: 11 }}>
              DB: {info.db}
              <br />
              파일: {info.images.replace(/images$/, '')}
            </div>
          </div>

          <div style={{ fontSize: 12, color: T.textDim, marginBottom: 6 }}>
            새 폴더 경로 (전체 경로로 입력)
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Input
              placeholder="예: D:\PaperLibrary  또는  C:\Users\me\Documents\논문"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onPressEnter={() => path.trim() && apply(path.trim())}
            />
            <Button
              type="primary"
              loading={busy}
              disabled={!path.trim() || path.trim() === (info.library_root ?? '')}
              onClick={() => apply(path.trim())}
            >
              변경
            </Button>
          </div>

          {!info.is_default && (
            <Button size="small" style={{ marginTop: 8 }} onClick={() => apply(null)}>
              기본 폴더로 되돌리기
            </Button>
          )}

          <div style={{ fontSize: 11, color: T.textFaint, marginTop: 14, lineHeight: 1.8 }}>
            · 지정한 폴더 안에 <code>papers.db</code>, <code>uploads/</code>, <code>images/</code> 가
            만들어지고 <b>독립된 라이브러리</b>가 됩니다.
            <br />· 기존 논문은 <b>지워지지 않습니다</b> — 원래 폴더에 그대로 남아 있고, 경로를
            되돌리면 다시 나타납니다.
            <br />· 공용 PC라면 사람마다 다른 폴더를 지정해 서로의 논문이 섞이지 않게 할 수 있습니다.
            <br />· 네트워크 드라이브도 됩니다(느릴 수 있음).
          </div>
        </>
      )}
    </Modal>
  )
}

export const LibraryPathButton = ({ onOpen }: { onOpen: () => void }) => (
  <button type="button" className="pa-ghost hide-sm" onClick={onOpen} title="논문 저장 폴더 변경">
    <FolderOpenOutlined />
    저장 폴더
  </button>
)
