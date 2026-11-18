const inrFmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const inrWhole = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

/** ₹1,23,456.50 – Indian digit grouping. */
export const inr = (n: number) => inrFmt.format(n)
export const inrShort = (n: number) => inrWhole.format(n)

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** Whole days [first, last] for a period preset, in the browser's local time. Weeks run Monday–Sunday. */
export function periodDates(range: string, from = '', to = ''): { first?: string; last?: string } {
  const t = new Date()
  if (range === 'all') return {}
  if (range === 'custom') return { first: from || undefined, last: to || undefined }
  if (range === 'today') return { first: ymd(t), last: ymd(t) }
  if (range === 'this_week') {
    const mon = new Date(t.getFullYear(), t.getMonth(), t.getDate() - ((t.getDay() + 6) % 7))
    return { first: ymd(mon), last: ymd(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 6)) }
  }
  if (range === 'last_month') return { first: ymd(new Date(t.getFullYear(), t.getMonth() - 1, 1)), last: ymd(new Date(t.getFullYear(), t.getMonth(), 0)) }
  if (range === 'this_year') return { first: `${t.getFullYear()}-01-01`, last: `${t.getFullYear()}-12-31` }
  return { first: ymd(new Date(t.getFullYear(), t.getMonth(), 1)), last: ymd(new Date(t.getFullYear(), t.getMonth() + 1, 0)) } // this_month
}
export const todayStr = () => ymd(new Date())
