<script setup lang="ts">
import { Head, router } from '@inertiajs/vue3'
import { useEchoPublic } from '@laravel/echo-vue'

interface FactSource {
  organization: string
  url: string
}

interface FactItem {
  id: number
  broadcast: {
    id: number
    name: string
    closed_at: string | null
  }
  claim: {
    text: string
  }
  analysis: {
    summary: string
    sources: FactSource[]
  }
  overall_verdict: string
  created_at: string | null
}

interface FactReceivedEvent {
  id: number
  created_at: string | null
}

const props = defineProps<{
  facts: FactItem[]
}>()

const eventName = '.fact.received'
const channelName = 'facts'
function listener(_event: FactReceivedEvent) {
  router.reload({
    only: ['facts'],
  })
}

useEchoPublic<FactReceivedEvent>(channelName, eventName, listener)
</script>

<template>
  <Head title="Facts" />

  <main class="mx-auto max-w-4xl px-6 py-10">
    <h1 class="mb-6 text-3xl font-bold">
      Facts
    </h1>

    <p v-if="props.facts.length === 0" class="text-gray-500">
      No facts received yet.
    </p>

    <ul v-else class="space-y-4">
      <li
        v-for="fact in props.facts"
        :key="fact.id"
        class="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
      >
        <div class="mb-2 flex items-center justify-between gap-2 text-xs text-gray-500">
          <span>{{ fact.created_at ?? 'Unknown date' }}</span>
          <span class="flex items-center gap-1.5">
            <span class="font-medium text-gray-700">{{ fact.broadcast.name }}</span>
            <span
              v-if="fact.broadcast.closed_at"
              class="rounded-full bg-red-100 px-1.5 py-0.5 text-red-600"
            >Closed</span>
            <span
              v-else
              class="rounded-full bg-green-100 px-1.5 py-0.5 text-green-700"
            >Live</span>
          </span>
        </div>

        <h2 class="mb-2 text-lg font-semibold">
          {{ fact.claim.text }}
        </h2>
        <p class="mb-3 text-sm text-gray-700">
          {{ fact.analysis.summary }}
        </p>

        <p class="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
          Overall verdict
        </p>
        <p class="mb-4 text-sm font-semibold">
          {{ fact.overall_verdict }}
        </p>

        <div v-if="fact.analysis.sources.length > 0" class="space-y-1 text-sm">
          <p class="font-medium">
            Sources
          </p>
          <ul class="list-inside list-disc">
            <li v-for="source in fact.analysis.sources" :key="`${source.organization}-${source.url}`">
              <a
                :href="source.url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-blue-600 underline"
              >
                {{ source.organization }}
              </a>
            </li>
          </ul>
        </div>
      </li>
    </ul>
  </main>
</template>
