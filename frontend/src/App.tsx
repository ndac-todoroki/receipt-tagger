import { createSignal, For, onCleanup, Show } from 'solid-js'
import { createStore } from 'solid-js/store'
import { analyze, type AnalyzeResult, type JudgeStatus, type Progress, type Stage } from './api'

const yen = (n: number | null) => (n === null ? '—' : `¥${n.toLocaleString()}`)

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
      <div class="card">
        <label class="upload">
          <input
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
          <span class="muted">画像を選ぶと、すぐに解析を始めます</span>
        </label>
      </div>

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
        <table>
          <thead>
            <tr>
              <th>品目</th>
              <th class="num">数量</th>
              <th class="num">金額</th>
              <Show when={r().granularity === 'per_item'}>
                <th>大分類</th>
                <th>ジャンル</th>
              </Show>
            </tr>
          </thead>
          <tbody>
            <For each={r().items}>
              {(item, i) => (
                <tr>
                  <td>{item.name}</td>
                  <td class="num">{item.quantity}</td>
                  <td class="num">
                    {yen(item.amount)}
                    <Show when={item.discount > 0}>
                      <span class="discount">（割引 {yen(item.discount)}）</span>
                    </Show>
                  </td>
                  <Show when={r().granularity === 'per_item'}>
                    <td>{item.category ?? <span class="muted">—</span>}</td>
                    <td>
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
                    </td>
                  </Show>
                </tr>
              )}
            </For>
          </tbody>
          <tfoot>
            <tr>
              <th colspan="2">合計</th>
              <td class="num">{yen(r().total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </>
  )
}
