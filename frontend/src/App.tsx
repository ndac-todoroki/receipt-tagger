import { createSignal, For, Show } from 'solid-js'
import { createStore } from 'solid-js/store'
import { analyze, type AnalyzeResult, type JudgeStatus } from './api'

const yen = (n: number | null) => (n === null ? '—' : `¥${n.toLocaleString()}`)

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

export default function App() {
  const [file, setFile] = createSignal<File | null>(null)
  const [loading, setLoading] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)
  const [result, setResult] = createStore<{ value: AnalyzeResult | null }>({ value: null })

  const submit = async () => {
    const f = file()
    if (!f) return
    setLoading(true)
    setError(null)
    try {
      setResult('value', await analyze(f))
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
        <input
          type="file"
          accept="image/*"
          capture="environment"
          onChange={(e) => setFile(e.currentTarget.files?.[0] ?? null)}
        />
        <button disabled={!file() || loading()} onClick={submit}>
          {loading() ? '解析中…' : '解析する'}
        </button>
        <Show when={loading()}>
          <p class="muted">文字の読み取りに10秒ほどかかります</p>
        </Show>
      </div>

      <Show when={error()}>
        <p class="error">{error()}</p>
      </Show>

      <Show when={result.value}>
        {(r) => (
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
                    <th>数量</th>
                    <th>金額</th>
                    <Show when={r().granularity === 'per_item'}>
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
                          <td>
                            <GenreCell
                              {...item}
                              onChoose={(g) =>
                                setResult('value', 'items', i(), { genre: g, status: 'confirmed' })
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
        )}
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
