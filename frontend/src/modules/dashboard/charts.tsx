import { useState, type ReactNode } from 'react'

export interface Datum { label: string; value: number; hint?: string }

/** A chart always has a table view, so nothing depends on colour or hover alone. */
export function ChartCard({ title, subtitle, data, valueLabel = 'Trips', format = String, children }: {
  title: string; subtitle?: string; data: Datum[]; valueLabel?: string; format?: (n: number) => string; children: ReactNode
}) {
  const [table, setTable] = useState(false)
  return (
    <section className="chart-card viz" aria-label={title}>
      <div className="chart-head">
        <div><h3>{title}</h3>{subtitle && <div className="sub">{subtitle}</div>}</div>
        <button className="linkbtn" onClick={() => setTable(!table)} aria-pressed={table}>{table ? 'Show chart' : 'Show table'}</button>
      </div>
      {!data.length || data.every((d) => !d.value) ? <div className="empty-chart">No data for this period.</div> : table ? (
        <table className="table"><thead><tr><th>Item</th><th style={{ textAlign: 'right' }}>{valueLabel}</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.label}><td>{d.label}</td><td style={{ textAlign: 'right' }}>{format(d.value)}</td></tr>)}</tbody></table>
      ) : children}
    </section>
  )
}

/** Horizontal bars: value at the tip, thin marks with a rounded data end, one baseline. */
export function BarList({ data, format = (n: number) => String(n) }: { data: Datum[]; format?: (n: number) => string }) {
  const max = Math.max(...data.map((d) => d.value), 1)
  return (
    <div className="barlist">
      {data.map((d) => (
        <div className="barrow" key={d.label} title={d.hint ?? `${d.label}: ${format(d.value)}`}>
          <span className="name">{d.label}</span>
          <span className="bartrack"><span className="bar" style={{ width: `${(d.value / max) * 100}%`, maxWidth: 'calc(100% - 44px)' }} /><span className="barval">{format(d.value)}</span></span>
        </div>
      ))}
    </div>
  )
}

/** Vertical columns with a per-column tooltip (hover or keyboard focus). */
export function Columns({ data, every = 1, format = String }: { data: Datum[]; every?: number; format?: (n: number) => string }) {
  const max = Math.max(...data.map((d) => d.value), 1)
  return (
    <>
      <div className="cols" role="img" aria-label={data.map((d) => `${d.label}: ${format(d.value)}`).join(', ')}>
        {data.map((d) => (
          <div className="col" key={d.label} tabIndex={0}>
            {d.value > 0 && <span className="tip">{d.label} · {format(d.value)}</span>}
            <span style={{ height: `${(d.value / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="xlabels" aria-hidden>{data.map((d, i) => <span key={d.label}>{i % every === 0 ? d.label : ''}</span>)}</div>
    </>
  )
}

/** Single-series line for the daily trend: 2px line, 8px end dot with a surface ring. */
export function Trend({ data, format = String }: { data: Datum[]; format?: (n: number) => string }) {
  const W = 480, H = 150, P = 8
  const max = Math.max(...data.map((d) => d.value), 1)
  const x = (i: number) => P + (data.length === 1 ? (W - 2 * P) / 2 : (i * (W - 2 * P)) / (data.length - 1))
  const y = (v: number) => H - P - (v / max) * (H - 2 * P)
  const [hover, setHover] = useState<number | null>(null)
  const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ')
  const last = data[data.length - 1]
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={data.map((d) => `${d.label}: ${d.value}`).join(', ')}
        onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((t) => <line key={t} x1={P} x2={W - P} y1={y(max * t)} y2={y(max * t)} stroke="var(--grid)" strokeWidth="1" />)}
        <polyline points={pts} fill="none" stroke="var(--series-1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => (
          <rect key={d.label} x={x(i) - (W / data.length) / 2} y={0} width={W / data.length} height={H} fill="transparent"
            onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0} />
        ))}
        <circle cx={x(data.length - 1)} cy={y(last.value)} r="4" fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2" />
        {hover !== null && <><line x1={x(hover)} x2={x(hover)} y1={P} y2={H - P} stroke="var(--axis)" /><circle cx={x(hover)} cy={y(data[hover].value)} r="4" fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2" /></>}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted-ink)' }}><span>{data[0].label}</span><span>{last.label}</span></div>
      {hover !== null && <div className="col" style={{ position: 'absolute', top: 0, left: `${(x(hover) / W) * 100}%`, height: 0 }}><span className="tip" style={{ display: 'block' }}>{data[hover].label} · {format(data[hover].value)}</span></div>}
    </div>
  )
}

/** Progress toward a target; the track is a lighter step of the same hue. */
export function Meter({ value, label }: { value: number; label: string }) {
  return (
    <div role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div style={{ height: 10, borderRadius: 99, background: 'color-mix(in srgb, var(--series-1) 18%, var(--surface))', overflow: 'hidden' }} className="viz">
        <div style={{ width: `${Math.min(100, value)}%`, height: '100%', background: 'var(--series-1)', borderRadius: 99 }} />
      </div>
    </div>
  )
}
