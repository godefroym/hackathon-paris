<script lang="ts" setup>
import type { FactCheckEventPayload, FactCheckPayload } from '../../../types'
import type { BannerItem } from '../../../lib/factCheck'
import { useEchoPublic } from '@laravel/echo-vue'
import { buildBannersFromPayload, buildTimeLabel, normalizeVerdict } from '../../../lib/factCheck'
import { normalizeFactCheckPayload } from '../../../types'

interface FactCheckHistoryResponse {
  items?: FactCheckEventPayload[]
}

const banners = ref<BannerItem[]>([])
const seenBannerIds = new Set<string>()

function upsertPayload(payload: FactCheckPayload): void {
  if (payload.clear) {
    banners.value = []
    seenBannerIds.clear()
    return
  }

  const nextItems = buildBannersFromPayload(payload)
  for (const item of nextItems) {
    if (seenBannerIds.has(item.id)) {
      continue
    }
    seenBannerIds.add(item.id)
    banners.value.unshift(item)
  }
}

async function hydrateHistory(): Promise<void> {
  try {
    const response = await fetch('/api/stream/fact-check/history?limit=100', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) {
      return
    }

    const data = (await response.json()) as FactCheckHistoryResponse
    const items = Array.isArray(data.items) ? data.items : []

    banners.value = []
    seenBannerIds.clear()

    for (const event of items) {
      upsertPayload(normalizeFactCheckPayload(event))
    }
  } catch {
    // Ignore bootstrap errors and rely on realtime events.
  }
}

function ingestEvent(event: FactCheckEventPayload): void {
  upsertPayload(normalizeFactCheckPayload(event))
}

function verdictLabel(banner: BannerItem): string {
  const verdict = normalizeVerdict(banner.verdict)
  if (verdict.length === 0) {
    return banner.tone === 'false' ? 'inaccurate' : 'context'
  }
  return verdict
}

onMounted(() => {
  void hydrateHistory()
})

useEchoPublic<FactCheckEventPayload>(
  'stream.fact-check',
  '.stream.fact-check.content-updated',
  (event) => {
    ingestEvent(event)
  },
)
</script>

<template>
  <UApp>
    <main class="fc-monitor-root">
      <header class="fc-monitor-header">
        <div>
          <p class="fc-monitor-kicker">
            Fact-check monitor
          </p>
          <h1 class="fc-monitor-title">
            Recent fact-check banners
          </h1>
        </div>
        <div class="fc-monitor-count">
          {{ banners.length }} item<span v-if="banners.length !== 1">s</span>
        </div>
      </header>

      <section class="fc-monitor-list">
        <article
          v-for="banner in banners"
          :key="banner.id"
          class="fc-monitor-card"
          :class="{
            'fc-monitor-card-false': banner.tone === 'false',
            'fc-monitor-card-context': banner.tone === 'context',
          }"
        >
          <div class="fc-monitor-meta">
            <span class="fc-monitor-chip">{{ banner.label }}</span>
            <span class="fc-monitor-chip fc-monitor-chip-secondary">
              {{ verdictLabel(banner) }}
            </span>
            <span class="fc-monitor-time">
              {{ buildTimeLabel(banner.switchedAtMs, banner.switchedAt) }}
            </span>
          </div>

          <h2 class="fc-monitor-headline">
            {{ banner.headline }}
          </h2>

          <p class="fc-monitor-body">
            {{ banner.body }}
          </p>

          <div
            v-if="banner.sources.length > 0"
            class="fc-monitor-sources"
          >
            <a
              v-for="source in banner.sources"
              :key="`${banner.id}-${source.url}`"
              class="fc-monitor-link"
              :href="source.url"
              target="_blank"
              rel="noreferrer noopener"
            >
              <span class="fc-monitor-link-org">{{ source.organization }}</span>
              <span class="fc-monitor-link-url">{{ source.url }}</span>
            </a>
          </div>
        </article>

        <div
          v-if="banners.length === 0"
          class="fc-monitor-empty"
        >
          No banners yet.
        </div>
      </section>
    </main>
  </UApp>
</template>

<style scoped>
.fc-monitor-root {
  min-height: 100vh;
  padding: 2rem;
  background:
    radial-gradient(circle at top left, rgba(214, 48, 49, 0.08), transparent 30%),
    radial-gradient(circle at top right, rgba(241, 196, 15, 0.12), transparent 28%),
    linear-gradient(180deg, #f6f1e8 0%, #efe8db 100%);
  color: #1c130f;
}

.fc-monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 1rem;
  margin: 0 auto 1.5rem;
  max-width: 90rem;
}

.fc-monitor-kicker {
  margin: 0 0 0.35rem;
  font-size: 0.9rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #8c5b46;
}

.fc-monitor-title {
  margin: 0;
  font-size: clamp(2rem, 4vw, 3.6rem);
  line-height: 0.95;
  font-weight: 900;
}

.fc-monitor-count {
  font-size: 0.95rem;
  font-weight: 700;
  color: #7d685c;
}

.fc-monitor-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 90rem;
  margin: 0 auto;
}

.fc-monitor-card {
  width: 100%;
  border-radius: 1.5rem;
  border: 1px solid rgba(28, 19, 15, 0.08);
  padding: 1.5rem 1.7rem;
  box-shadow: 0 18px 50px rgba(62, 39, 35, 0.12);
}

.fc-monitor-card-false {
  background: linear-gradient(135deg, rgba(255, 235, 235, 0.98), rgba(255, 214, 214, 0.96));
}

.fc-monitor-card-context {
  background: linear-gradient(135deg, rgba(255, 248, 221, 0.98), rgba(255, 237, 171, 0.96));
}

.fc-monitor-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: center;
  margin-bottom: 1rem;
}

.fc-monitor-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.35rem 0.7rem;
  border-radius: 999px;
  background: rgba(28, 19, 15, 0.08);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.fc-monitor-chip-secondary {
  background: rgba(255, 255, 255, 0.5);
}

.fc-monitor-time {
  margin-left: auto;
  font-size: 0.9rem;
  font-weight: 700;
  color: #725d50;
}

.fc-monitor-headline {
  margin: 0 0 0.8rem;
  font-size: clamp(1.6rem, 3vw, 2.5rem);
  line-height: 1.05;
  font-weight: 900;
}

.fc-monitor-body {
  margin: 0;
  font-size: clamp(1.15rem, 2vw, 1.5rem);
  line-height: 1.4;
  font-weight: 600;
}

.fc-monitor-sources {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  margin-top: 1.25rem;
}

.fc-monitor-link {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.9rem 1rem;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.58);
  color: #1c130f;
  text-decoration: none;
  border: 1px solid rgba(28, 19, 15, 0.08);
  word-break: break-word;
}

.fc-monitor-link:hover {
  background: rgba(255, 255, 255, 0.74);
}

.fc-monitor-link-org {
  font-size: 0.92rem;
  font-weight: 800;
}

.fc-monitor-link-url {
  font-size: 0.92rem;
  line-height: 1.35;
  color: #6d574d;
}

.fc-monitor-empty {
  padding: 3rem 1.5rem;
  text-align: center;
  font-size: 1.05rem;
  font-weight: 700;
  color: #7d685c;
  border: 2px dashed rgba(28, 19, 15, 0.12);
  border-radius: 1.5rem;
  background: rgba(255, 255, 255, 0.35);
}

@media (max-width: 768px) {
  .fc-monitor-root {
    padding: 1rem;
  }

  .fc-monitor-header {
    flex-direction: column;
    align-items: start;
  }

  .fc-monitor-time {
    margin-left: 0;
  }
}
</style>
