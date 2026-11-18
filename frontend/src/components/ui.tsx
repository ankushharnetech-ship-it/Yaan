import { X } from 'lucide-react'
import { createPortal } from 'react-dom'
import { cloneElement, isValidElement, useEffect, useId, useRef, type ReactElement, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

/** Accessible form field: the label is tied to the control, and hints/errors are announced with it. */
export function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  const id = useId()
  const note = error ? `${id}-err` : hint ? `${id}-hint` : undefined
  const isControl = isValidElement(children) && (children.type === TextInput || children.type === SelectInput || children.type === 'textarea' || children.type === 'input' || children.type === 'select')
  const control = isControl
    ? cloneElement(children as ReactElement<Record<string, unknown>>, { id, 'aria-describedby': note, 'aria-invalid': error ? true : undefined })
    : children
  return (
    <div className="field" role={isControl ? undefined : 'group'} aria-label={isControl ? undefined : label}>
      <label htmlFor={isControl ? id : undefined}>{label}</label>
      {control}
      {hint && !error && <span id={`${id}-hint`} className="muted" style={{ fontSize: 12.5 }}>{hint}</span>}
      {error && <span id={`${id}-err`} className="error-text" role="alert">{error}</span>}
    </div>
  )
}

export const TextInput = (p: InputHTMLAttributes<HTMLInputElement>) => <input className="input" {...p} />

export const SelectInput = (p: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select className="input" {...p} />
)

// Open dialogs, topmost last: only the topmost one reacts to Escape/Tab (a form can open from inside another dialog).
const openModals: symbol[] = []
let pageOverflow = '' // body overflow before the first dialog opened, restored when the last one closes

/**
 * Dialog rendered into <body> through a portal, so it is always positioned against the viewport and never
 * trapped inside (or clipped by) the card/animated container it was opened from.
 */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const id = Symbol('modal')
    if (!openModals.length) pageOverflow = document.body.style.overflow
    openModals.push(id)
    const opener = document.activeElement as HTMLElement | null
    document.body.style.overflow = 'hidden' // the page behind the dialog must not scroll
    const focusables = () => Array.from(box.current?.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []).filter((el) => !el.hasAttribute('disabled'))
    ;(box.current?.querySelector<HTMLElement>('input, select, textarea') ?? focusables()[0] ?? box.current)?.focus()
    const h = (e: KeyboardEvent) => {
      if (openModals[openModals.length - 1] !== id) return
      if (e.key === 'Escape') { closeRef.current(); return }
      if (e.key !== 'Tab') return
      const f = focusables()
      if (!f.length) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', h)
    return () => {
      window.removeEventListener('keydown', h)
      openModals.splice(openModals.indexOf(id), 1)
      document.body.style.overflow = openModals.length ? 'hidden' : pageOverflow
      opener?.focus?.()
    }
  }, [])
  return createPortal(
    <div className="modal-scrim" onMouseDown={onClose}>
      <div ref={box} tabIndex={-1} className="modal card" role="dialog" aria-modal="true" aria-label={title}
        style={{ width: wide ? 'min(720px, 100%)' : 'min(520px, 100%)' }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2>{title}</h2>
          <button className="btn" aria-label="Close" onClick={onClose} style={{ width: 36, padding: 0 }}><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{subtitle && <p className="muted" style={{ margin: '4px 0 0' }}>{subtitle}</p>}</div>
      <div style={{ display: 'flex', gap: 8 }}>{actions}</div>
    </div>
  )
}

export function Badge({ tone, children }: { tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral'; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <>
      <PageHead title={title} />
      <div className="card muted">This module is scheduled for {phase}.</div>
    </>
  )
}
