<script lang="ts" setup>
import type {
  FactCheckEventPayload,
  FactCheckPayload,
} from '../../../types'
import { useEchoPublic } from '@laravel/echo-vue'
import { AnimatePresence, Motion } from 'motion-v'
import ContentState from '../../../components/overlays/fact-check/ContentState.vue'
import LoadingState from '../../../components/overlays/fact-check/LoadingState.vue'
import {
  emptyFactCheckPayload,
  normalizeFactCheckPayload,
} from '../../../types'

const index = tv({
  slots: {
    root: 'relative h-screen w-screen',
    panel: 'absolute top-8 right-8',
    card: 'ring-0 relative overflow-hidden shadow-lg',
  },
  variants: {
    hasFactCheck: {
      true: {
        card: 'h-full',
      },
    },
  },
})

const payload = ref<FactCheckPayload>(emptyFactCheckPayload)
const hasReceivedPayload = ref(false)

const hasClaim = computed(() => payload.value.claim.text.trim().length > 0)
const hasAnalysisSummary = computed(() => payload.value.analysis.summary.trim().length > 0)
const hasSources = computed(() => payload.value.analysis.sources.length > 0)
const hasVerdict = computed(() => payload.value.overall_verdict.trim().length > 0)

const hasFactCheck = computed(
  () => hasClaim.value || hasAnalysisSummary.value || hasSources.value || hasVerdict.value,
)

const showFactCheck = computed(() => hasReceivedPayload.value && hasFactCheck.value)

const ui = computed(() => index({ hasFactCheck: showFactCheck.value }))

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
    payload.value = normalizeFactCheckPayload(event)
    hasReceivedPayload.value = true
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
    payload.value = normalizeFactCheckPayload(event)
    hasReceivedPayload.value = true
  },
)
</script>

<template>
  <UApp>
    <div :class="ui.root()">
    <AnimatePresence mode="popLayout">
      <Motion
        v-if="!showFactCheck"
        :class="ui.panel()"
        :initial="{
            opacity: 0,
            transform: 'translateX(-20px)'
        }"
        :animate="{
            opacity: 1,
            transform: 'translateX(0)'
        }"
        :exit="{
            opacity: 0,
            transform: 'translateX(-20px)'
        }"
        :transition="{
            duration: 0.8,
        }"
      >
        <UCard :class="ui.card()" class="w-60">
          <LoadingState  />
        </UCard>

      </Motion>
      <Motion
        v-else
        :class="ui.panel()"
        :initial="{
            opacity: 0,
            transform: 'translateX(-20px)'
        }"
        :animate="{
            opacity: 1,
            transform: 'translateX(0)'
        }"
        :exit="{
            opacity: 0,
            transform: 'translateX(-20px)'
        }"
        :transition="{
            duration: 0.8,
        }"
      >
        <UCard :class="ui.card()" class="w-md">
          <ContentState
            :payload="payload"
            :has-claim="hasClaim"
            :has-analysis-summary="hasAnalysisSummary"
            :has-sources="hasSources"
            :has-verdict="hasVerdict"
           />
        </UCard>
      </Motion>
    </AnimatePresence>
    </div>
  </UApp>
</template>
