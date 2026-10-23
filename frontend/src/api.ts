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
  genre: string | null
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
}

export async function analyze(file: File): Promise<AnalyzeResult> {
  const body = new FormData()
  body.append('image', file)
  const res = await fetch('/api/analyze', { method: 'POST', body })
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => null)
    throw new Error(detail ?? `解析に失敗しました（${res.status}）`)
  }
  return res.json()
}
