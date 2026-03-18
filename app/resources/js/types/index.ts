export interface FactCheckSource {
  organization: string
  url: string
}

export interface FactCheckPayload {
  claim: {
    text: string
  }
  analysis: {
    summary: string
    sources: FactCheckSource[]
  }
  overall_verdict: string
  scene: string
  switched_at_ms: number
  switched_at: string | null
  clear: boolean
}

export type FactCheckEventPayload = Partial<FactCheckPayload>

export const emptyFactCheckPayload: FactCheckPayload = {
  claim: {
    text: '',
  },
  analysis: {
    summary: '',
    sources: [],
  },
  overall_verdict: '',
  scene: '',
  switched_at_ms: 0,
  switched_at: null,
  clear: false,
}

export function normalizeFactCheckPayload(event: FactCheckEventPayload): FactCheckPayload {
  return {
    claim: {
      text: event.claim?.text ?? '',
    },
    analysis: {
      summary: event.analysis?.summary ?? '',
      sources: event.analysis?.sources ?? [],
    },
    overall_verdict: event.overall_verdict ?? '',
    scene: event.scene ?? '',
    switched_at_ms: event.switched_at_ms ?? 0,
    switched_at: event.switched_at ?? null,
    clear: event.clear ?? false,
  }
}
