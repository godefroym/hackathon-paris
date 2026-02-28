<script lang="ts" setup>
import StreamFactCheckController from '../actions/App/Http/Controllers/Api/StreamFactCheckController'

interface FactCheckSource {
  organization: string
  url: string
}

interface FactCheckPayload {
  claim: {
    text: string
  }
  analysis: {
    summary: string
    sources: FactCheckSource[]
  }
  overall_verdict: string
}

const form = ref<FactCheckPayload>({
  claim: {
    text: '',
  },
  analysis: {
    summary: '',
    sources: [
      {
        organization: '',
        url: '',
      },
    ],
  },
  overall_verdict: 'partially_accurate',
})

const response = ref<Record<string, unknown> | null>(null)
const errors = ref<Record<string, string[]>>({})
const isSubmitting = ref(false)

async function submit(): Promise<void> {
  isSubmitting.value = true
  errors.value = {}

  const route = StreamFactCheckController()

  const result = await fetch(route.url, {
    method: route.method.toUpperCase(),
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(form.value),
  })

  const data = await result.json()

  if (!result.ok) {
    errors.value = (data.errors ?? {}) as Record<string, string[]>
    isSubmitting.value = false

    return
  }

  response.value = data as Record<string, unknown>
  isSubmitting.value = false
}

function addSource(): void {
  form.value.analysis.sources.push({
    organization: '',
    url: '',
  })
}

function removeSource(index: number): void {
  if (form.value.analysis.sources.length === 1) {
    return
  }

  form.value.analysis.sources.splice(index, 1)
}

</script>

<template>
  <UApp>
    <div class="max-w-4xl mx-auto p-6 space-y-6">
      <h1 class="text-2xl font-semibold">
        Stream fact-check payload
      </h1>

      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-2">
          <label class="block text-sm font-medium">Claim text</label>
          <textarea
            v-model="form.claim.text"
            rows="3"
            class="w-full rounded-md border border-default px-3 py-2"
          />
          <p v-if="errors['claim.text']" class="text-sm text-error">
            {{ errors['claim.text'][0] }}
          </p>
        </div>

        <div class="space-y-2">
          <label class="block text-sm font-medium">Analysis summary</label>
          <textarea
            v-model="form.analysis.summary"
            rows="4"
            class="w-full rounded-md border border-default px-3 py-2"
          />
          <p v-if="errors['analysis.summary']" class="text-sm text-error">
            {{ errors['analysis.summary'][0] }}
          </p>
        </div>

        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <label class="block text-sm font-medium">Sources</label>
            <button type="button" class="text-sm underline" @click="addSource">
              Add source
            </button>
          </div>

          <div
            v-for="(source, index) in form.analysis.sources"
            :key="index"
            class="rounded-md border border-default p-3 space-y-2"
          >
            <input
              v-model="source.organization"
              type="text"
              placeholder="Organization"
              class="w-full rounded-md border border-default px-3 py-2"
            >
            <input
              v-model="source.url"
              type="url"
              placeholder="https://..."
              class="w-full rounded-md border border-default px-3 py-2"
            >

            <button type="button" class="text-sm underline" @click="removeSource(index)">
              Remove
            </button>
          </div>

          <p v-if="errors['analysis.sources']" class="text-sm text-error">
            {{ errors['analysis.sources'][0] }}
          </p>
          <p v-if="errors['analysis.sources.0.organization']" class="text-sm text-error">
            {{ errors['analysis.sources.0.organization'][0] }}
          </p>
          <p v-if="errors['analysis.sources.0.url']" class="text-sm text-error">
            {{ errors['analysis.sources.0.url'][0] }}
          </p>
        </div>

        <div class="space-y-2">
          <label class="block text-sm font-medium">Overall verdict</label>
          <select
            v-model="form.overall_verdict"
            class="w-full rounded-md border border-default px-3 py-2"
          >
            <option value="accurate">
              accurate
            </option>
            <option value="partially_accurate">
              partially_accurate
            </option>
            <option value="inaccurate">
              inaccurate
            </option>
            <option value="unverified">
              unverified
            </option>
          </select>
          <p v-if="errors['overall_verdict']" class="text-sm text-error">
            {{ errors['overall_verdict'][0] }}
          </p>
        </div>

        <button class="rounded-md bg-primary text-inverted px-4 py-2" :disabled="isSubmitting">
          {{ isSubmitting ? 'Sending...' : 'Send to stream endpoint' }}
        </button>
      </form>

      <div v-if="response" class="space-y-2">
        <h2 class="text-lg font-semibold">
          API response
        </h2>
        <pre class="rounded-md border border-default p-3 overflow-x-auto text-xs">{{ JSON.stringify(response, null, 2) }}</pre>
      </div>
    </div>
  </UApp>
</template>
