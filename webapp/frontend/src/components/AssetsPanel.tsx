// 시각자료·레퍼런스 뷰어 — 선택된 논문의 그림/표/참고문헌.
// 탭은 평평하게, 활성 탭만 진한 글자 + 보라 하단 표시(theme.ts에서 설정).

import { ExperimentOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Empty, Image, Spin, Table, Tabs } from 'antd'
import { useEffect, useState } from 'react'
import { api, type AssetItem, type Assets } from '../api'
import { glossify } from '../glossary'
import { useApp } from '../store'
import { T } from '../theme'

const SCROLL: React.CSSProperties = {
  overflowY: 'auto',
  maxHeight: 'calc(100vh - 190px)',
  marginRight: -6,
  paddingRight: 6,
}

function Figure({ item, showTable }: { item: AssetItem; showTable?: boolean }) {
  return (
    <div style={{ marginBottom: 22 }}>
      {/* 원본 비율 그대로 (width만 맞추고 height auto). 흰 배경 그림이 뜨지 않게 보더로 감싼다 */}
      <Image
        src={item.image_url}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        wrapperStyle={{
          width: '100%',
          border: `1px solid ${T.border}`,
          borderRadius: T.radiusMd,
          overflow: 'hidden',
          background: '#fff',
          display: 'block',
        }}
      />
      <div style={{ fontSize: 12, color: T.textDim, marginTop: 8, lineHeight: 1.6 }}>
        {item.caption_ko || item.caption_en || `p.${item.page}`}
      </div>
      {item.analysis_ko && (
        <div
          className="ai-response"
          style={{ marginTop: 8, fontSize: 12, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}
        >
          <div style={{ fontSize: 10, letterSpacing: '0.06em', color: T.ai, marginBottom: 4 }}>
            AI FIGURE ANALYSIS
          </div>
          {glossify(item.analysis_ko)}
        </div>
      )}
      {showTable && item.table_rows && item.table_rows.length > 1 && (
        <Table
          size="small"
          pagination={false}
          scroll={{ x: true }}
          style={{ marginTop: 10 }}
          dataSource={item.table_rows.slice(1).map((r, i) => ({ key: i, ...r }))}
          columns={item.table_rows[0].map((h, i) => ({
            title: h || `열${i + 1}`,
            dataIndex: i,
            ellipsis: true,
          }))}
        />
      )}
    </div>
  )
}

export function AssetsPanel() {
  const { message } = App.useApp()
  const selectedId = useApp((s) => s.selectedId)
  const documents = useApp((s) => s.documents)
  const [assets, setAssets] = useState<Assets | null>(null)
  const [loading, setLoading] = useState(false)

  const doc = documents.find((d) => d.doc_id === selectedId)

  const load = () => {
    if (!selectedId) return
    setLoading(true)
    api
      .getAssets(selectedId)
      .then(setAssets)
      .catch(() => setAssets(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!selectedId || doc?.status !== 'ready') {
      setAssets(null)
      return
    }
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, doc?.status])

  const startAnalysis = async () => {
    if (!selectedId) return
    try {
      const r = await api.analyzeFigures(selectedId)
      if (r.locked) message.warning(r.message)
      else if (!r.started) message.info(r.message)
      else message.success(`${r.message} 잠시 후 새로고침(↻)으로 확인하세요.`)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  if (!selectedId)
    return <Empty description="논문을 선택하세요" style={{ marginTop: 80, color: T.textFaint }} />
  if (doc?.status !== 'ready')
    return (
      <Empty description="처리가 끝나면 표시됩니다" style={{ marginTop: 80, color: T.textFaint }} />
    )
  if (loading) return <Spin style={{ display: 'block', margin: '80px auto' }} />
  if (!assets) return <Empty description="자료 없음" style={{ marginTop: 80 }} />

  return (
    <Tabs
      size="small"
      style={{ height: '100%' }}
      tabBarExtraContent={
        <div style={{ display: 'flex', gap: 6 }}>
          <Button size="small" icon={<ReloadOutlined />} onClick={load} title="새로고침" />
          <Button
            size="small"
            icon={<ExperimentOutlined />}
            onClick={startAnalysis}
            title="그림·표를 AI로 분석 (유료 — 그림당 약 ₩3~6, 하드락 시 차단)"
          >
            AI 분석
          </Button>
        </div>
      }
      items={[
        {
          key: 'fig',
          label: `그림 ${assets.figures.length}`,
          children: (
            <div style={SCROLL}>
              {assets.figures.map((f) => (
                <Figure key={f.order} item={f} />
              ))}
              {!assets.figures.length && <Empty description="그림 없음" />}
            </div>
          ),
        },
        {
          key: 'tbl',
          label: `표 ${assets.tables.length}`,
          children: (
            <div style={SCROLL}>
              {assets.tables.map((t) => (
                <Figure key={t.order} item={t} showTable />
              ))}
              {!assets.tables.length && <Empty description="표 없음" />}
            </div>
          ),
        },
        {
          key: 'ref',
          label: `참고문헌 ${assets.references.length}`,
          children: (
            <div style={SCROLL}>
              {assets.references.map((r) => (
                <div
                  key={r.idx}
                  style={{
                    display: 'flex',
                    gap: 10,
                    fontSize: 12,
                    color: T.textDim,
                    padding: '8px 0',
                    borderBottom: `1px solid ${T.border}`,
                    lineHeight: 1.6,
                  }}
                >
                  <span
                    style={{ color: T.textFaint, flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}
                  >
                    {r.idx}
                  </span>
                  <span>{r.raw}</span>
                </div>
              ))}
              {!assets.references.length && <Empty description="참고문헌을 찾지 못했습니다" />}
            </div>
          ),
        },
      ]}
    />
  )
}
