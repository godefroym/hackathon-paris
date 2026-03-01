<script setup lang="ts">
import { router } from '@inertiajs/vue3'
import { useClipboard } from '@vueuse/core'

interface BroadcastItem {
  id: number
  uuid: string
  name: string
  facts_count: number
  closed_at: string | null
  summary: string | null
  created_at: string | null
}

const props = defineProps<{
  broadcast: BroadcastItem
}>()

const { copy, copied } = useClipboard({ source: props.broadcast.uuid })

function closeBroadcast() {
  if (!confirm(`Close broadcast "${props.broadcast.name}"? This will trigger a TL;DR synthesis and no new facts will be accepted.`)) {
    return
  }
  router.post(`/admin/broadcasts/${props.broadcast.id}/close`)
}
</script>

<template>
  <li
    class="rounded-lg border p-4"
    :class="broadcast.closed_at ? 'border-gray-200 bg-gray-50' : 'border-gray-300 bg-white'"
  >
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-mono text-xs text-gray-400">#{{ broadcast.id }}</span>
          <span class="font-semibold">{{ broadcast.name }}</span>
          <span
            v-if="broadcast.closed_at"
            class="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
          >
            Closed
          </span>
          <span
            v-else
            class="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
          >
            Live
          </span>
        </div>
        <p class="mt-1 text-xs text-gray-500">
          {{ broadcast.facts_count }} fact{{ broadcast.facts_count !== 1 ? 's' : '' }} checked
          <span v-if="broadcast.closed_at">
            · Closed {{ new Date(broadcast.closed_at).toLocaleString() }}
          </span>
        </p>
        <div class="mt-1.5 flex items-center gap-1.5">
          <span class="select-all font-mono text-xs text-gray-400">{{ broadcast.uuid }}</span>
          <button
            class="rounded px-1.5 py-0.5 text-xs font-medium transition-colors"
            :class="copied ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'"
            @click="copy(broadcast.uuid)"
          >
            {{ copied ? 'Copied!' : 'Copy' }}
          </button>
        </div>
      </div>

      <button
        v-if="!broadcast.closed_at"
        class="shrink-0 rounded border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
        @click="closeBroadcast"
      >
        Close broadcast
      </button>
    </div>

    <div
      v-if="broadcast.summary"
      class="mt-4 rounded-md bg-white p-3 text-sm text-gray-700 shadow-sm"
    >
      <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
        TL;DR – AI Synthesis
      </p>
      <p class="whitespace-pre-wrap leading-relaxed">
        {{ broadcast.summary }}
      </p>
    </div>

    <div
      v-else-if="broadcast.closed_at"
      class="mt-4 rounded-md bg-gray-100 p-3 text-sm text-gray-400 italic"
    >
      Synthesis pending or no facts were recorded.
    </div>
  </li>
</template>
