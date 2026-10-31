import { createSignal, For, onCleanup, Show } from 'solid-js'
import { createStore } from 'solid-js/store'
import { analyze, type AnalyzeResult, type JudgeStatus, type Progress, type Stage } from './api'

const yen = (n: number | null) => (n === null ? '—' : `¥${n.toLocaleString()}`)

// index.css の --cat-0 〜 --cat-5
const CATEGORY_COLORS = 6

const STAGES: { stage: Stage; label: string }[] = [
  { stage: 'reading', label: '文字の読み取り' },
  { stage: 'store', label: '店の検索' },
  { stage: 'items', label: 'ジャンルの判定' },
]

function GenreCell(props: {
  genre: string | null
  status: JudgeStatus
  candidates: string[]
  onChoose: (genre: string) => void
}) {
  return (
    <Show
      when={props.status === 'uncertain'}
      fallback={
        props.status === 'unknown' ? (
          <span class="muted">判定不能</span>
        ) : (
          // 値引きの行など、分類の対象外はジャンルを出さない
          <>{props.genre ?? <span class="muted">—</span>}</>
        )
      }
    >
      <select onChange={(e) => props.onChoose(e.currentTarget.value)}>
        <option value="">未確定（選択）</option>
        <For each={props.candidates}>{(c) => <option value={c}>{c}</option>}</For>
      </select>
    </Show>
  )
}

// 待ち順・今の段階・経過時間と目安を出す
// estimate は receivedAt の時点から終わるまでの目安（秒）。経過は submittedAt から数える
function ProgressCard(props: {
  progress: Progress | null
  estimate: number | null
  submittedAt: number
  receivedAt: number
  now: number
}) {
  const elapsed = () => Math.max(0, (props.now - props.submittedAt) / 1000)
  const sinceEstimate = () => Math.max(0, (props.now - props.receivedAt) / 1000)
  const estimate = () => props.estimate
  const queued = () => props.progress?.type === 'queued'
  const currentStage = () => {
    const p = props.progress
    return p?.type === 'stage' ? p.stage : null
  }
  const stageIndex = () => STAGES.findIndex((s) => s.stage === currentStage())

  return (
    <div class="card progress" role="status" aria-live="polite">
      <div class="progress-head">
        <span class="spinner" aria-hidden="true" />
        <strong>
          <Show when={queued()} fallback="解析しています">
            順番を待っています
          </Show>
        </strong>
      </div>
      <Show when={props.progress?.type === 'queued' && props.progress}>
        {(p) => <p>あなたの前に {p().ahead} 件の解析があります</p>}
      </Show>
      <ol class="stages">
        <For each={STAGES}>
          {(s, i) => (
            <li
              classList={{
                done: !queued() && i() < stageIndex(),
                current: !queued() && i() === stageIndex(),
              }}
            >
              {s.label}
            </li>
          )}
        </For>
      </ol>
      {/* 時間ではなく段階で進める。終わった段階を塗り、今の段階は点滅させる */}
      <div class="bar" aria-hidden="true">
        <For each={STAGES}>
          {(_, i) => (
            <div
              classList={{
                done: !queued() && i() < stageIndex(),
                current: !queued() && i() === stageIndex(),
              }}
            />
          )}
        </For>
      </div>
      <p class="muted">
        経過 {Math.floor(elapsed())} 秒
        <Show when={estimate()}>
          {(e) => <> ／ 残り 約 {Math.max(1, Math.round(e() - sinceEstimate()))} 秒</>}
        </Show>
      </p>
    </div>
  )
}

export default function App() {
  const [imageUrl, setImageUrl] = createSignal<string | null>(null)
  const [loading, setLoading] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)
  const [progress, setProgress] = createSignal<Progress | null>(null)
  // 目安の時間は届いた時点からの残りなので、受け取った時刻も持っておく。
  // 段階の知らせには目安が無いので、待ち・開始の知らせの目安を使い続ける
  const [estimate, setEstimate] = createSignal<number | null>(null)
  const [receivedAt, setReceivedAt] = createSignal(Date.now())
  const [submittedAt, setSubmittedAt] = createSignal(Date.now())
  const [now, setNow] = createSignal(Date.now())
  const [result, setResult] = createStore<{ value: AnalyzeResult | null }>({ value: null })

  const timer = setInterval(() => setNow(Date.now()), 500)
  onCleanup(() => clearInterval(timer))

  // ページのどこにドロップしてもよい。子要素の上を通るたびに dragenter / dragleave が
  // 対で起きるので、回数を数えてページの外に出たかを判断する
  const [dragging, setDragging] = createSignal(false)
  let dragDepth = 0
  const hasFiles = (e: DragEvent) => e.dataTransfer?.types.includes('Files') ?? false
  const onDragEnter = (e: DragEvent) => {
    if (!hasFiles(e)) return
    dragDepth += 1
    setDragging(true)
  }
  const onDragLeave = (e: DragEvent) => {
    if (!hasFiles(e)) return
    dragDepth = Math.max(0, dragDepth - 1)
    if (dragDepth === 0) setDragging(false)
  }
  const onDragOver = (e: DragEvent) => {
    if (!hasFiles(e)) return
    // 既定の動作（ブラウザが画像を開く）を止めて、ドロップを受け付ける
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = loading() ? 'none' : 'copy'
  }
  const onDrop = (e: DragEvent) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    dragDepth = 0
    setDragging(false)
    const f = [...(e.dataTransfer?.files ?? [])].find((file) => file.type.startsWith('image/'))
    if (loading()) return
    if (f) void start(f)
    else setError('画像のファイルをドロップしてください')
  }
  window.addEventListener('dragenter', onDragEnter)
  window.addEventListener('dragleave', onDragLeave)
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('drop', onDrop)
  onCleanup(() => {
    window.removeEventListener('dragenter', onDragEnter)
    window.removeEventListener('dragleave', onDragLeave)
    window.removeEventListener('dragover', onDragOver)
    window.removeEventListener('drop', onDrop)
  })

  const start = async (file: File) => {
    const old = imageUrl()
    if (old) URL.revokeObjectURL(old)
    setImageUrl(URL.createObjectURL(file))
    setResult('value', null)
    setError(null)
    setProgress(null)
    setEstimate(null)
    setSubmittedAt(Date.now())
    setReceivedAt(Date.now())
    setLoading(true)
    try {
      setResult(
        'value',
        await analyze(file, (p) => {
          setProgress(p)
          if (p.type !== 'stage') {
            setEstimate(p.estimate_seconds)
            setReceivedAt(Date.now())
          }
        }),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main>
      <h1>レシート仕分け</h1>
      {/* ブラウザ標準のボタンは見た目が合わないので、input は見えなくしてエリア全体で選ばせる */}
      <label classList={{ dropzone: true, dragging: dragging(), disabled: loading() }}>
        <input
          class="visually-hidden"
          type="file"
          accept="image/*"
          capture="environment"
          disabled={loading()}
          onChange={(e) => {
            const f = e.currentTarget.files?.[0]
            // 同じファイルを選び直しても onChange が起きるよう、値を空に戻す
            e.currentTarget.value = ''
            if (f) void start(f)
          }}
        />
        <Show
          when={dragging()}
          fallback={
            <>
              <strong>{loading() ? '解析中です' : 'レシートの画像を選ぶ'}</strong>
              <span class="muted">
                {loading()
                  ? '終わると次の画像を選べます'
                  : 'クリックして選ぶか、ページのどこかにドラッグ＆ドロップ。すぐに解析を始めます'}
              </span>
            </>
          }
        >
          <strong>{loading() ? '解析中は受け付けられません' : 'ドロップして解析開始'}</strong>
        </Show>
      </label>

      <Show when={imageUrl()}>
        <div class="panes">
          <div class="pane-image">
            <img src={imageUrl()!} alt="解析するレシート" />
          </div>
          <div class="pane-result">
            <Show when={loading()}>
              <ProgressCard
                progress={progress()}
                estimate={estimate()}
                submittedAt={submittedAt()}
                receivedAt={receivedAt()}
                now={now()}
              />
            </Show>
            <Show when={error()}>
              <p class="error">{error()}</p>
            </Show>
            <Show when={result.value}>{(r) => <ResultCards result={r()} setResult={setResult} />}</Show>
          </div>
        </div>
      </Show>

      <footer class="muted">
        店舗情報: ©{' '}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          OpenStreetMap contributors
        </a>
      </footer>
    </main>
  )
}

function ResultCards(props: {
  result: AnalyzeResult
  setResult: ReturnType<typeof createStore<{ value: AnalyzeResult | null }>>[1]
}) {
  const r = () => props.result
  const setResult = props.setResult
  const perItem = () => r().granularity === 'per_item'
  // 大分類の色は、設定（labels.yaml）での大分類の並び順で決める
  const categories = () => [...new Set(Object.values(r().item_categories))]
  const categoryColor = (category: string | null) => {
    const i = category === null ? -1 : categories().indexOf(category)
    return i < 0 ? 'var(--border)' : `var(--cat-${i % CATEGORY_COLORS})`
  }
  return (
    <>
      <div class="card">
        <div>
          店名: <strong>{r().store.name ?? '読み取れませんでした'}</strong>
        </div>
        <div>
          店ジャンル:{' '}
          <GenreCell
            {...r().store}
            onChoose={(g) => setResult('value', 'store', { genre: g, status: 'confirmed' })}
          />
        </div>
      </div>

      <Show when={r().consistency.ok === false}>
        <p class="warn">
          品目の合計（{yen(r().consistency.items_sum)}）と合計金額（
          {yen(r().consistency.total)}）が一致しません。読み取り誤りの可能性があります。
        </p>
      </Show>

      <div class="card">
        <div classList={{ items: true, 'per-item': perItem() }} role="table">
          <div class="item-row head" role="row">
            <span class="name" role="columnheader">品目</span>
            <span class="qty" role="columnheader">数量</span>
            <span class="amount" role="columnheader">金額</span>
            <Show when={perItem()}>
              <span class="category" role="columnheader">大分類</span>
              <span class="genre" role="columnheader">ジャンル</span>
            </Show>
          </div>
          <For each={r().items}>
            {(item, i) => (
              <div
                class="item-row"
                role="row"
                style={{ '--cat': categoryColor(item.category) }}
              >
                <span class="name" role="cell">{item.name}</span>
                <span class="qty" role="cell">{item.quantity}</span>
                <span class="amount" role="cell">
                  {yen(item.amount)}
                  <Show when={item.discount > 0}>
                    <span class="discount">（割引 {yen(item.discount)}）</span>
                  </Show>
                </span>
                <Show when={perItem()}>
                  <span class="category" role="cell">
                    {item.category ?? <span class="muted">—</span>}
                  </span>
                  <span class="genre" role="cell">
                    <GenreCell
                      {...item}
                      onChoose={(g) =>
                        setResult('value', 'items', i(), {
                          genre: g,
                          category: r().item_categories[g] ?? null,
                          status: 'confirmed',
                        })
                      }
                    />
                  </span>
                </Show>
              </div>
            )}
          </For>
          <div class="item-row total" role="row">
            <span class="name" role="rowheader">合計</span>
            <span class="amount" role="cell">{yen(r().total)}</span>
          </div>
        </div>
      </div>
    </>
  )
}
