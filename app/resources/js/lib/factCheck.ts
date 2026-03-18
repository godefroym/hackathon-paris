import type { FactCheckPayload, FactCheckSource } from '../types'

export type BannerTone = 'false' | 'context'

export interface BannerItem {
  id: string
  tone: BannerTone
  label: string
  headline: string
  body: string
  sources: FactCheckSource[]
  verdict: string
  switchedAtMs: number
  switchedAt: string | null
}

export function normalizeVerdict(value: string): string {
  return value.trim().toLowerCase()
}

export function isFalseLike(payload: FactCheckPayload): boolean {
  const verdict = normalizeVerdict(payload.overall_verdict)
  const summary = payload.analysis.summary.toLowerCase()
  const claim = payload.claim.text.toLowerCase()
  const looksStatistical = /\d/.test(claim)
    || claim.includes('pourcent')
    || claim.includes('pourcentage')
    || claim.includes('plus de')
    || claim.includes('moins de')
    || claim.includes('plus que')
    || claim.includes('moins que')
    || claim.includes('moyenne')
    || claim.includes('millions')
    || claim.includes('milliards')
    || claim.includes('litres')
    || claim.includes('kg')
    || claim.includes('kilogrammes')

  const strongFalseSummary = summary.includes('❌')
    || summary.includes(' faux')
    || summary.startsWith('faux')
    || summary.includes('erron')
    || summary.includes('mensonger')
    || summary.includes('mensongere')
    || summary.includes('mensongère')
    || summary.includes('incorrect')
    || summary.includes('et non')

  return verdict.includes('inaccurate')
    || verdict.includes('false')
    || verdict.includes('faux')
    || strongFalseSummary
    || (looksStatistical && strongFalseSummary)
}

export function hasRenderableContent(payload: FactCheckPayload): boolean {
  return payload.claim.text.trim().length > 0 || payload.analysis.summary.trim().length > 0
}

export function buildTimeLabel(switchedAtMs: number, switchedAt: string | null): string {
  if (switchedAt) {
    const parsed = new Date(switchedAt)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    }
  }

  if (switchedAtMs > 0) {
    const parsed = new Date(switchedAtMs)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    }
  }

  return 'live'
}

export function shortSourceLabel(source: FactCheckSource): string {
  try {
    const hostname = new URL(source.url).hostname.replace(/^www\./, '')
    const organization = source.organization.trim()
    if (organization.length > 0) {
      return `${organization} · ${hostname}`
    }
    return hostname
  } catch {
    if (source.organization.trim().length > 0) {
      return source.organization.trim()
    }
    return source.url
  }
}

export function buildBannersFromPayload(payload: FactCheckPayload): BannerItem[] {
  if (!hasRenderableContent(payload)) {
    return []
  }

  const switchedAtMs = payload.switched_at_ms || Date.now()
  const switchedAt = payload.switched_at
  const verdict = payload.overall_verdict.trim()
  const items: BannerItem[] = []
  const claimText = payload.claim.text.trim()
  const summaryText = payload.analysis.summary.trim()

  if (claimText && isFalseLike(payload)) {
    items.push({
      id: `${switchedAtMs}-claim`,
      tone: 'false',
      label: 'False claim',
      headline: claimText,
      body: summaryText || verdict || 'inaccurate',
      sources: payload.analysis.sources,
      verdict,
      switchedAtMs,
      switchedAt,
    })
  }
  else if (summaryText) {
    items.push({
      id: `${switchedAtMs}-context`,
      tone: 'context',
      label: 'Context',
      headline: claimText || 'Additional context',
      body: summaryText,
      sources: payload.analysis.sources,
      verdict,
      switchedAtMs,
      switchedAt,
    })
  }
  else if (!summaryText && claimText) {
    items.push({
      id: `${switchedAtMs}-claim`,
      tone: 'context',
      label: 'Statement',
      headline: claimText,
      body: verdict || 'under review',
      sources: payload.analysis.sources,
      verdict,
      switchedAtMs,
      switchedAt,
    })
  }

  return items
}
