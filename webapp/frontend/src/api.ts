// 백엔드 API 클라이언트. vite proxy 덕분에 상대경로 그대로 쓴다.

export type DocStatus =
  | 'pending' | 'extracting' | 'translating' | 'indexing' | 'ready' | 'failed'

export interface DocumentMeta {
  doc_id: string
  title: string
  filename?: string
  status: DocStatus
  progress: number
  page_count: number
  error: string | null
  cover_url?: string | null // PDF 1페이지 렌더 표지 (로컬 생성)

  // 유료 산출물 현황 — '완료'가 번역인지 그림분석인지 구분하고, 재과금을 막는 근거
  text_blocks?: number
  translated_blocks?: number
  translated?: boolean
  translate_complete?: boolean
  figure_blocks?: number
  analyzed_figures?: number
  analyzed?: boolean
  analyze_complete?: boolean
}

export interface Block {
  order: number
  kind: 'text' | 'image' | 'table'
  page: number
  text_en: string
  text_ko: string
  image_url?: string
  table_rows: string[][] | null
  is_caption: boolean
  /** 캡션 블록이 어느 그림에 붙었는가. false 면 짝 없는 캡션 — 숨기지 않고 본문에 보여 준다 */
  attached?: boolean
  analysis_ko?: string
}

export interface AssetItem {
  order: number
  page: number
  image_url: string
  caption_en: string
  caption_ko: string
  table_rows: string[][] | null
  analysis_ko?: string
}

export interface Assets {
  figures: AssetItem[]
  tables: AssetItem[]
  references: { idx: number; raw: string }[]
}

export interface Citation {
  title: string
  gcs_uri: string
  snippet: string
}

/** 로컬 검색 결과 — 논문 1편과 그 안에서 매칭된 구절들 */
export interface SearchResult {
  doc_id: string
  title: string
  score: number
  passages: { page: number; order: number; text: string }[]
  /** AI 가 통째로 읽은 논문 — 문단은 화면에 다시 싣지 않는다 */
  full?: boolean
  /** 고른 논문이 아니라 참고로 붙인 다른 논문 */
  ref?: boolean
}

/** 「이 논문만」으로 물었을 때 AI에게 실제로 건넨 분량 — "다 읽었다"고 잘못 믿지 않게 화면에 그대로 보여 준다 */
export interface Coverage {
  doc_id: string
  title: string
  pages: number
  read_until_page: number
  read_chars: number
  total_chars: number
  truncated: boolean
}

export interface ChatResponse {
  // keyword=로컬 구절만(0원) · local_llm=PC 안의 AI 요약(0원) · api=API 키 요약 · cloud=Vertex 요약(크레딧)
  // locked=하드락 · fallback=쓸 자격증명 없음
  mode: 'keyword' | 'local_llm' | 'api' | 'cloud' | 'locked' | 'fallback'
  answer: string
  results: SearchResult[]
  citations: Citation[]
  coverage?: Coverage[]
  memories_used?: string[]
  memory_hints?: MemoryItem[]
  figures_used?: string[]
  scope?: string | null // 특정 논문으로 한정해 답한 경우 그 논문 제목
}

export interface LibraryPaths {
  library_root: string | null
  is_default: boolean
  db: string
  uploads: string
  images: string
  default_root: string
  doc_count: number
  db_exists: boolean
}

/** /api/health — 지금 돈이 나가는 구성인지, 번역이 어디로 나가는지 */
export interface Health {
  paid_apis_enabled: boolean
  offline_mode: boolean
  memory_enabled?: boolean
  /** keyword 면 AI 요약 없이 찾은 구절만 보여 준다(0원·외부 전송 없음) */
  search_mode?: string
  translate_provider?: string
  translate_model?: string | null
  translate_cost?: { per_page_krw: number | null; per_paper_krw: number | null } | null
}

export interface MemoryItem {
  id?: number
  question: string
  answer_summary: string
  doc_titles?: string
  created_at?: string
}

async function json<T>(p: Promise<Response>): Promise<T> {
  const res = await p
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`)
  return (await res.json()) as T
}

export const api = {
  upload: (file: File, opts?: { translate?: boolean; analyze?: boolean }) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('translate', String(opts?.translate ?? false))
    fd.append('analyze', String(opts?.analyze ?? false))
    return json<{ doc_id: string; title: string }>(
      fetch('/api/documents', { method: 'POST', body: fd }),
    )
  },
  getHealth: () => json<Health>(fetch('/api/health')),
  listDocuments: () => json<DocumentMeta[]>(fetch('/api/documents')),
  getDocument: (id: string) => json<DocumentMeta>(fetch(`/api/documents/${id}`)),
  getBlocks: (id: string) =>
    json<{ blocks: Block[] }>(fetch(`/api/documents/${id}/blocks`)),
  getAssets: (id: string) => json<Assets>(fetch(`/api/documents/${id}/assets`)),
  // docIds = 라이브러리에서 체크한 논문들 → 그 논문들을 집중적으로 읽고 답한다
  chat: (question: string, docIds?: string[] | null) =>
    json<ChatResponse>(
      fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, doc_ids: docIds ?? [] }),
      }),
    ),

  // 유료 API 스위치 (상단 배지 클릭)
  togglePaid: (enabled: boolean) =>
    json<{ paid_apis_enabled: boolean; message: string }>(post('/api/paid/toggle', { enabled })),

  // ── 사용자별 API 키 ──────────────────────────────
  listUsers: () => json<{ users: UserRow[]; active: string | null }>(fetch('/api/users')),
  addUser: (username: string, password: string, api_key: string) =>
    json<{ username: string }>(
      post('/api/users', { username, password, api_key }),
    ),
  verifyUser: (username: string, password: string) =>
    json<{ ok: boolean; api_key: string }>(
      post(`/api/users/${encodeURIComponent(username)}/verify`, { password }),
    ),
  updateKey: (username: string, password: string, api_key: string) =>
    json<{ ok: boolean }>(
      put(`/api/users/${encodeURIComponent(username)}/key`, { password, api_key }),
    ),
  deleteUser: (username: string, password: string) =>
    json<{ ok: boolean }>(
      post(`/api/users/${encodeURIComponent(username)}/delete`, { password }),
    ),
  activateUser: (username: string, password: string) =>
    json<{ ok: boolean; active: string }>(
      post(`/api/users/${encodeURIComponent(username)}/activate`, { password }),
    ),
  deactivate: () => json<{ ok: boolean }>(post('/api/users/deactivate', {})),

  // ── 자격증명 3종 (무료키/유료키/크레딧) ──────────
  getCredentials: (username: string) =>
    json<Credentials>(fetch(`/api/users/${encodeURIComponent(username)}/credentials`)),
  revealCredential: (username: string, password: string, kind: CredKind) =>
    json<{ kind: CredKind; value: string }>(
      post(`/api/users/${encodeURIComponent(username)}/credentials/reveal`, { password, kind }),
    ),
  saveCredential: (username: string, password: string, kind: CredKind, value: string) =>
    json<{ ok: boolean; credentials: Credentials }>(
      put(`/api/users/${encodeURIComponent(username)}/credentials`, { password, kind, value }),
    ),
  setPreferred: (username: string, password: string, kind: CredKind) =>
    json<{ ok: boolean; preferred: CredKind }>(
      put(`/api/users/${encodeURIComponent(username)}/preferred`, { password, kind }),
    ),

  analyzeFigures: (docId: string) =>
    json<{ started: boolean; pending: number; locked?: boolean; message: string }>(
      post(`/api/documents/${docId}/figures/analyze`, {}),
    ),
  translateDoc: (docId: string) =>
    json<{ started: boolean; pending: number; locked?: boolean; message: string }>(
      post(`/api/documents/${docId}/translate`, {}),
    ),

  // ── 논문 저장 폴더 ────────────────────────────────
  getLibraryPath: () => json<LibraryPaths>(fetch('/api/library/path')),
  setLibraryPath: (path: string | null) =>
    json<LibraryPaths>(put('/api/library/path', { path })),

  // ── 챗봇 대화 기억 (맞춤형 스킬) ──────────────────
  listMemory: () =>
    json<{ enabled: boolean; memories: Required<MemoryItem>[] }>(fetch('/api/memory')),
  toggleMemory: (enabled: boolean) =>
    json<{ enabled: boolean }>(post('/api/memory/toggle', { enabled })),
  deleteMemory: (id: number) => json<{ ok: boolean }>(post(`/api/memory/${id}/delete`, {})),
  clearMemory: () => json<{ deleted: number }>(post('/api/memory/clear', {})),
}

export type CredKind = 'free' | 'paid' | 'credit'

export interface Credentials {
  preferred: CredKind
  credit_enabled?: boolean // false면 크레딧 칸을 숨긴다(사내망 등 gcloud 로그인 차단 환경)
  free: { set: boolean; masked: string }
  paid: { set: boolean; masked: string }
  credit: { set: boolean; masked: string }
}

export interface UserRow {
  username: string
  has_key: boolean
  credentials?: Credentials
}

function post(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
function put(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
