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
  }
}
