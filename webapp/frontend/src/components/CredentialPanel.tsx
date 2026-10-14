// 자격증명 입력 패널 — **API 키 1칸**이 기본.
//
// 예전에는 무료키·유료키·크레딧 3칸이었는데, 무료/유료는 코드상 완전히 같은 것이라
// 사용자에게 혼란만 줬다(앱은 키 등급을 판별하지 못한다). 그래서 API 키 1칸으로 줄이고,
// 크레딧(GCP)은 ENABLE_CREDIT=true 인 환경에서만 보조 옵션으로 노출한다.
//
// 표시 원칙: 화면에는 **항상 마스킹된 값**만 나온다(AIzaSy••••••••••••wXyZ).
// 원문은 비밀번호를 확인해야 서버가 내려주고, 수정란에만 채워진다.
// 실제 저장 위치는 이 PC의 로컬 SQLite(Article_Battery/crawler/papers.db) — 외부 전송 없음.

import {
  CheckCircleFilled,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { App, Button, Input, Radio, Tag, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { api, type CredKind, type Credentials } from '../api'
import { T } from '../theme'

const HELP_APIKEY = `Google AI Studio에서 발급한 Gemini API 키입니다 (aistudio.google.com/apikey).
무료 키·유료 키 **아무거나** 넣으면 됩니다 — 앱은 등급을 구분하지 않고 그대로 사용합니다.

【내 키가 무료인지 유료인지 구분하는 법】
· 결제 계정을 연결하지 않았다면 → 무료 등급. 요금 0원, 대신 분당·일일 요청 수 제한이 있고
  ⚠️ 구글이 입력 내용을 모델 개선에 사용할 수 있습니다(공개 논문만 넣으세요).
· 결제 계정을 연결했다면 → 유료 등급. 사용한 만큼 본인에게 청구되고,
  입력 데이터는 모델 학습에 쓰이지 않습니다.

【유료 등급일 때 대략 비용 (gemini-2.5-flash 기준)】
· 논문 번역 1편 ≈ ₩121   · 그림·표 분석 1장 ≈ ₩3~6 (논문 1편 ≈ ₩30)
· 챗봇 AI 요약 1회 ≈ 수 원 이하

※ 무료 등급의 제공 범위·기간은 구글 정책에 따라 바뀔 수 있으니
   현재 조건은 ai.google.dev/pricing 에서 확인하세요.`

const HELP_CREDIT = `GCP(Google Cloud) 프로젝트를 이용하는 경로입니다. **API 키가 아니라 프로젝트 ID**를 넣으세요.

· 이 PC에 gcloud 로그인이 되어 있어야 동작합니다 (gcloud auth login).
· 비용은 그 GCP 프로젝트의 크레딧/결제 계정에서 차감됩니다.
· 입력 데이터는 모델 학습에 쓰이지 않습니다.

【Vertex/GCP가 없어도 괜찮습니다】 이 칸을 비워두면 위의 API 키로만 동작합니다.
챗봇 요약도 API 키만으로 같은 역할을 합니다.`

const META: Record<
  CredKind,
  { label: string; hint: string; placeholder: string; tone: string; cost: string; help: string }
> = {
  free: {
    label: 'API 키',
    hint: '무료 키·유료 키 아무거나 넣으면 됩니다.',
    placeholder: 'AIza... (Gemini API 키)',
    tone: T.success,
    cost: '요금은 이 키의 등급에 따름',
    help: HELP_APIKEY,
  },
  // 예비 슬롯 — 새 UI에서는 노출하지 않는다(기존 사용자의 값은 폴백으로 계속 쓰인다)
  paid: {
    label: 'API 키 (예비)',
    hint: '예전 버전에서 등록한 두 번째 키. 첫 번째가 실패하면 자동으로 시도됩니다.',
    placeholder: 'AIza... (Gemini API 키)',
    tone: T.warning,
    cost: '요금은 이 키의 등급에 따름',
    help: HELP_APIKEY,
  },
  credit: {
    label: '크레딧 (GCP)',
    hint: 'API 키가 아니라 GCP 프로젝트 ID. 없으면 비워두세요 — API 키만으로 동작합니다.',
    placeholder: 'GCP 프로젝트 ID (예: my-project-1234)',
    tone: T.ai,
    cost: 'GCP 크레딧/결제계정에서 차감',
    help: HELP_CREDIT,
  },
}

export function CredentialPanel({ username }: { username: string }) {
  const { message } = App.useApp()
  const [cred, setCred] = useState<Credentials | null>(null)
  const [editing, setEditing] = useState<CredKind | null>(null)
  const [password, setPassword] = useState('')
  const [value, setValue] = useState('')
  const [step, setStep] = useState<'pw' | 'edit'>('pw')
  const [busy, setBusy] = useState(false)

  const refresh = () => api.getCredentials(username).then(setCred).catch(() => {})
  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username])

  const startEdit = (kind: CredKind) => {
    setEditing(kind)
    setStep('pw')
    setPassword('')
    setValue('')
  }

  const doReveal = async () => {
    if (!editing) return
    setBusy(true)
    try {
      const r = await api.revealCredential(username, password, editing)
      setValue(r.value)
      setStep('edit')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const doSave = async (clear = false) => {
    if (!editing) return
    setBusy(true)
    try {
      const r = await api.saveCredential(username, password, editing, clear ? '' : value.trim())
      setCred(r.credentials)
      message.success(clear ? `${META[editing].label} 삭제됨` : `${META[editing].label} 저장됨`)
      setEditing(null)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // 기본 옵션은 "선택 → 저장" 2단계. 선택만으론 저장되지 않고, 저장 시 비밀번호로 확인한다.
  const [pendingPref, setPendingPref] = useState<CredKind | null>(null)
  const [prefPw, setPrefPw] = useState('')

  const savePreferred = async () => {
    if (!pendingPref) return
    setBusy(true)
    try {
      await api.setPreferred(username, prefPw, pendingPref)
      message.success(`기본 옵션을 [${META[pendingPref].label}]로 저장했습니다.`)
      setPendingPref(null)
      setPrefPw('')
      refresh()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!cred) return null

  const shown = pendingPref ?? cred.preferred // 선택 중이면 그 값을 보여준다

  // 기본은 API 키 1칸. 크레딧은 켜진 환경에서만, 예비 칸은 이미 값이 있을 때만 보여준다.
  const kinds: CredKind[] = ['free']
  if (cred.paid.set) kinds.push('paid')
  if (cred.credit_enabled !== false) kinds.push('credit')
  const singleSlot = kinds.length === 1 // 칸이 하나면 라디오 선택 UI가 무의미

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${T.border}` }}>
      <div style={{ fontSize: 11, color: T.textFaint, marginBottom: 8, lineHeight: 1.6 }}>
        {singleSlot ? (
          <>
            번역·그림분석·챗봇 요약에 쓸 <b>Gemini API 키</b>를 등록하세요. 무료 키·유료 키
            아무거나 됩니다.
          </>
        ) : (
          <>
            번역·그림분석·챗봇 요약에 쓸 자격증명입니다. <b>기본으로 쓸 것</b>을 고른 뒤
            저장하세요. 고른 것이 실패하면 나머지를 순서대로 자동 시도합니다.
          </>
        )}
        {cred.credit_enabled === false && (
          <div style={{ marginTop: 4, color: T.textDim }}>
            🏢 이 환경은 <b>API 키 전용</b>입니다 (크레딧/Vertex 비활성화).
          </div>
        )}
      </div>

      <Radio.Group
        value={shown}
        onChange={(e) => setPendingPref(e.target.value as CredKind)}
        style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}
      >
        {kinds.map((kind) => {
          const m = META[kind]
          const slot = cred[kind]
          const isEditing = editing === kind
          return (
            <div
              key={kind}
              style={{
                border: `1px solid ${shown === kind ? m.tone : T.border}`,
                borderRadius: T.radiusMd,
                padding: '8px 10px',
                background: shown === kind ? T.hover : 'transparent',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {!singleSlot && <Radio value={kind} style={{ marginRight: 0 }} />}
                <span style={{ fontSize: 12, fontWeight: 500, color: m.tone }}>{m.label}</span>
                {/* 조건3: ? 에 마우스를 올리면 무료/유료 구분법과 단가 안내 */}
                <Tooltip
                  title={<div style={{ whiteSpace: 'pre-line', fontSize: 11 }}>{m.help}</div>}
                  overlayStyle={{ maxWidth: 460 }}
                  placement="right"
                >
                  <QuestionCircleOutlined
                    style={{ color: T.textFaint, fontSize: 11, cursor: 'help' }}
                  />
                </Tooltip>
                {slot.set ? (
                  <Tag
                    color="default"
                    style={{ fontSize: 10, margin: 0, fontFamily: 'monospace' }}
                    icon={<CheckCircleFilled style={{ color: T.success }} />}
                  >
                    {slot.masked}
                  </Tag>
                ) : (
                  <Tag style={{ fontSize: 10, margin: 0 }}>미등록</Tag>
                )}
                {!singleSlot && cred.preferred === kind && !pendingPref && (
                  <Tag color="processing" style={{ fontSize: 10, margin: 0 }}>
                    기본
                  </Tag>
                )}
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                  <Button
                    size="small"
                    type="text"
                    icon={slot.set ? <EditOutlined /> : <EyeOutlined />}
                    onClick={() => startEdit(kind)}
                    title={slot.set ? '수정' : '등록'}
                  />
                </span>
              </div>

              <div style={{ fontSize: 10, color: T.textFaint, marginTop: 4, marginLeft: 24 }}>
                {m.cost} · {m.hint}
              </div>

              {isEditing && (
                <div style={{ marginTop: 8, marginLeft: 24 }}>
                  {step === 'pw' ? (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Input.Password
                        autoFocus
                        size="small"
                        placeholder="비밀번호 확인"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onPressEnter={doReveal}
                      />
                      <Button size="small" type="primary" loading={busy} onClick={doReveal}>
                        확인
                      </Button>
                      <Button size="small" onClick={() => setEditing(null)}>
                        취소
                      </Button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Input.Password
                          autoFocus
                          size="small"
                          placeholder={m.placeholder}
                          value={value}
                          onChange={(e) => setValue(e.target.value)}
                          onPressEnter={() => doSave()}
                        />
                        {/* 입력란 바로 옆 ? — 무료/유료 구분법·단가 */}
                        <Tooltip
                          title={<div style={{ whiteSpace: 'pre-line', fontSize: 11 }}>{m.help}</div>}
                          overlayStyle={{ maxWidth: 460 }}
                          placement="right"
                        >
                          <QuestionCircleOutlined
                            style={{ color: T.textFaint, fontSize: 12, cursor: 'help', flexShrink: 0 }}
                          />
                        </Tooltip>
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <Button size="small" type="primary" loading={busy} onClick={() => doSave()}>
                          저장
                        </Button>
                        {slot.set && (
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={busy}
                            onClick={() => doSave(true)}
                          >
                            삭제
                          </Button>
                        )}
                        <Button size="small" onClick={() => setEditing(null)}>
                          취소
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </Radio.Group>

      {/* 기본 옵션을 바꿨을 때만 나타나는 저장 바 (비밀번호 확인 후 저장) */}
      {pendingPref && pendingPref !== cred.preferred && (
        <div
          style={{
            marginTop: 8,
            padding: '8px 10px',
            border: `1px solid ${T.primary}`,
            borderRadius: T.radiusMd,
            background: T.hover,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <div style={{ fontSize: 11, color: T.text }}>
            기본 옵션을 <b style={{ color: META[pendingPref].tone }}>{META[pendingPref].label}</b>
            (으)로 바꿉니다. 저장하려면 비밀번호를 입력하세요.
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Input.Password
              autoFocus
              size="small"
              placeholder="비밀번호"
              value={prefPw}
              onChange={(e) => setPrefPw(e.target.value)}
              onPressEnter={savePreferred}
            />
            <Button size="small" type="primary" loading={busy} onClick={savePreferred}>
              저장
            </Button>
            <Button
              size="small"
              onClick={() => {
                setPendingPref(null)
                setPrefPw('')
              }}
            >
              취소
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
