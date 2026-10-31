// inference/src/receipt_app/schemas.py と同じ形を保つ

export type JudgeStatus = 'confirmed' | 'uncertain' | 'unknown'

export type StoreResult = {
  name: string | null
  genre: string | null
  status: JudgeStatus
  candidates: string[]
}

export type ItemResult = {
  name: string
  quantity: number
  unit_price: number | null
  amount: number
  // その品目に付いた割引の額。amount は割引を引いた後の金額
  discount: number
  // genre は品目ジャンルの小分類、category はその大分類
  genre: string | null
  category: string | null
  confidence: number | null
  status: JudgeStatus
  candidates: string[]
}

export type AnalyzeResult = {
  store: StoreResult
  granularity: 'whole' | 'per_item'
  items: ItemResult[]
  total: number | null
  consistency: { ok: boolean | null; items_sum: number; total: number | null }
  // 品目ジャンルの小分類→大分類
  item_categories: Record<string, string>
}

// 解析の段階。inference/src/receipt_app/pipeline.py の Stage と同じ
export type Stage = 'reading' | 'store' | 'items'

// 解析の進み具合。estimate_seconds は、その時点から終わるまでの目安
export type Progress =
  | { type: 'queued'; ahead: number; estimate_seconds: number }
  | { type: 'started'; estimate_seconds: number }
  | { type: 'stage'; stage: Stage }

type StreamEvent =
  | Progress
  | { type: 'result'; result: AnalyzeResult }
  | { type: 'error'; detail: string }

// API は進み具合と結果を1行1つの JSON（NDJSON）で順に返す
export async function analyze(
  file: File,
  onProgress: (p: Progress) => void,
): Promise<AnalyzeResult> {
  const body = new FormData()
  body.append('image', file)
  const res = await fetch('/api/analyze', { method: 'POST', body })
  if (!res.ok || !res.body) {
    const detail = await res.json().then((j) => j.detail, () => null)
    throw new Error(detail ?? `解析に失敗しました（${res.status}）`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines.filter((l) => l.trim())) {
      const event = JSON.parse(line) as StreamEvent
      if (event.type === 'result') return event.result
      if (event.type === 'error') throw new Error(event.detail)
      onProgress(event)
    }
  }
  throw new Error('解析の途中で接続が切れました')
}
