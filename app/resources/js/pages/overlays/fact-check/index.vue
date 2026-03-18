<script lang="ts" setup>
import type {
  FactCheckEventPayload,
  FactCheckPayload,
} from '../../../types'
import type { BannerItem } from '../../../lib/factCheck'
import { useEchoPublic } from '@laravel/echo-vue'
import {
  emptyFactCheckPayload,
  normalizeFactCheckPayload,
} from '../../../types'
import {
  buildBannersFromPayload,
  buildTimeLabel,
  hasRenderableContent,
  isFalseLike,
  shortSourceLabel,
} from '../../../lib/factCheck'

const MAX_VISIBLE_BANNERS = 8

const banners = ref<BannerItem[]>([])
const seenBannerIds = new Set<string>()
const hydratedPayload = ref<FactCheckPayload>(emptyFactCheckPayload)

function ingestEvent(event: FactCheckEventPayload): void {
  const payload = normalizeFactCheckPayload(event)
  hydratedPayload.value = payload

  if (payload.clear) {
    banners.value = []
    seenBannerIds.clear()
    return
  }

  if (!hasRenderableContent(payload)) {
    return
  }

  const nextItems = buildBannersFromPayload(payload)
  let changed = false

  for (const item of nextItems) {
    if (seenBannerIds.has(item.id)) {
      continue
    }
    seenBannerIds.add(item.id)
    banners.value.push(item)
    changed = true
  }

  if (!changed) {
    return
  }

  if (banners.value.length > MAX_VISIBLE_BANNERS) {
    const overflow = banners.value.length - MAX_VISIBLE_BANNERS
    const removed = banners.value.splice(0, overflow)
    for (const item of removed) {
      seenBannerIds.delete(item.id)
    }
  }
}

async function hydrateLatestPayload(): Promise<void> {
  try {
    const response = await fetch('/api/stream/fact-check/latest', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) {
      return
    }
    const event = (await response.json()) as FactCheckEventPayload
    ingestEvent(event)
  } catch {
    // Ignore bootstrap errors and rely on realtime events.
  }
}

onMounted(() => {
  void hydrateLatestPayload()
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
    <div class="fc2-root">
      <div class="fc2-shell">
        <div class="fc2-status">
          <span class="fc2-status-dot" />
          <span>Fact-check live</span>
        </div>

        <div class="fc2-stack-viewport">
          <TransitionGroup
            name="fc2-stack"
            tag="div"
            class="fc2-stack-track"
          >
            <article
              v-for="banner in banners"
              :key="banner.id"
              class="fc2-banner"
              :class="{
                'fc2-banner-false': banner.tone === 'false',
                'fc2-banner-context': banner.tone === 'context',
              }"
            >
              <div class="fc2-banner-topline">
                <span class="fc2-banner-label">{{ banner.label }}</span>
                <span class="fc2-banner-time">
                  {{ buildTimeLabel(banner.switchedAtMs, banner.switchedAt) }}
                </span>
              </div>

              <h2 class="fc2-banner-headline">
                {{ banner.headline }}
              </h2>

              <p class="fc2-banner-body">
                {{ banner.body }}
              </p>

              <div
                v-if="banner.sources.length > 0"
                class="fc2-banner-sources"
              >
                <span
                  v-for="(source, index) in banner.sources.slice(0, 3)"
                  :key="`${banner.id}-${source.url}-${index}`"
                  class="fc2-source-chip"
                >
                  {{ shortSourceLabel(source) }}
                </span>
              </div>
            </article>
          </TransitionGroup>
        </div>
      </div>
    </div>
  </UApp>
</template>

<style scoped>
.fc2-root {
  min-height: 100vh;
  width: 100vw;
  overflow: hidden;
  pointer-events: none;
  background:
    radial-gradient(circle at 8% 100%, rgba(255, 230, 149, 0.18), transparent 30%),
    radial-gradient(circle at 92% 0%, rgba(255, 118, 134, 0.18), transparent 28%);
}

.fc2-shell {
  position: fixed;
  inset: 0;
  pointer-events: none;
}

.fc2-status {
  position: absolute;
  top: 1.5rem;
  right: 1.5rem;
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  border: 1px solid rgba(255, 255, 255, 0.42);
  background: rgba(18, 20, 26, 0.8);
  color: rgba(255, 248, 233, 0.94);
  border-radius: 999px;
  padding: 0.75rem 1.2rem;
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  box-shadow: 0 20px 45px rgba(6, 8, 12, 0.24);
  backdrop-filter: blur(14px);
}

.fc2-status-dot {
  width: 0.8rem;
  height: 0.8rem;
  border-radius: 999px;
  background: #7fffd4;
  box-shadow: 0 0 0 0.22rem rgba(127, 255, 212, 0.15);
}

.fc2-stack-viewport {
  position: absolute;
  top: 1.5rem;
  right: 1.5rem;
  bottom: 1.5rem;
  width: min(33vw, 40rem);
  overflow: hidden;
}

.fc2-stack-track {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.fc2-banner {
  position: relative;
  overflow: hidden;
  border-radius: 1.45rem;
  border: 1px solid rgba(255, 255, 255, 0.25);
  padding: 1.35rem 1.45rem 1.35rem 1.45rem;
  box-shadow: 0 28px 70px rgba(12, 14, 18, 0.18);
  backdrop-filter: blur(18px);
}

.fc2-banner::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(135deg, rgba(255, 255, 255, 0.12), transparent 45%);
  pointer-events: none;
}

.fc2-banner-false {
  background: linear-gradient(135deg, rgba(255, 232, 236, 0.98), rgba(255, 210, 218, 0.96));
  color: #641523;
  border-color: rgba(216, 86, 109, 0.42);
}

.fc2-banner-context {
  background: linear-gradient(135deg, rgba(255, 247, 212, 0.98), rgba(255, 234, 162, 0.97));
  color: #5f4700;
  border-color: rgba(225, 179, 28, 0.42);
}

.fc2-banner-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.55rem;
}

.fc2-banner-label,
.fc2-banner-time {
  position: relative;
  z-index: 1;
  font-size: 0.96rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.fc2-banner-headline,
.fc2-banner-body,
.fc2-banner-sources {
  position: relative;
  z-index: 1;
}

.fc2-banner-headline {
  margin: 0;
  font-size: clamp(1.5rem, 2.4vw, 2.3rem);
  line-height: 1.14;
  font-weight: 800;
}

.fc2-banner-body {
  margin: 0.65rem 0 0;
  font-size: clamp(1.18rem, 1.8vw, 1.62rem);
  line-height: 1.34;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 5;
  overflow: hidden;
}

.fc2-banner-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.8rem;
}

.fc2-source-chip {
  display: inline-flex;
  align-items: center;
  min-height: 2.25rem;
  border-radius: 999px;
  padding: 0.4rem 0.95rem;
  background: rgba(255, 255, 255, 0.48);
  border: 1px solid rgba(255, 255, 255, 0.5);
  font-size: 0.98rem;
  font-weight: 700;
}

.fc2-stack-enter-active,
.fc2-stack-leave-active,
.fc2-stack-move {
  transition: transform 520ms cubic-bezier(0.22, 1, 0.36, 1), opacity 520ms ease;
}

.fc2-stack-enter-from {
  opacity: 0;
  transform: translateY(32px) scale(0.98);
}

.fc2-stack-leave-to {
  opacity: 0;
  transform: translateY(-28px) scale(0.96);
}

@media (max-width: 768px) {
  .fc2-stack-viewport {
    top: 4.75rem;
    right: 1rem;
    bottom: 1rem;
    width: min(28rem, calc(100vw - 2rem));
  }

  .fc2-status {
    top: 1rem;
    right: 1rem;
  }

  .fc2-banner {
    padding: 1rem 1.05rem;
    border-radius: 1.2rem;
  }

  .fc2-banner-label,
  .fc2-banner-time {
    font-size: 0.82rem;
  }

  .fc2-banner-headline {
    font-size: clamp(1.2rem, 5vw, 1.6rem);
  }

  .fc2-banner-body {
    font-size: clamp(1rem, 4.2vw, 1.22rem);
  }

  .fc2-source-chip {
    min-height: 1.9rem;
    font-size: 0.82rem;
  }
}
</style>
