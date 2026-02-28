<script lang="ts">
import type { FactCheckPayload } from '../../../types'

const contentState = tv({
  slots: {
    root: 'h-full w-full',
    cardBody: 'h-full w-full',
    header: 'space-y-2',
    headerTop: 'flex items-start justify-between gap-3',
    headerTitle: 'text-xl font-semibold',
    poweredBy: 'font-light text-sm flex flex-row items-center gap-2',
    logoSmall: 'size-5',
    content: 'space-y-4',
    section: 'space-y-2',
    sectionTitle: 'text-xl font-semibold',
    sectionText: 'text-lg leading-relaxed',
    sectionTextMuted: 'text-muted text-sm leading-relaxed',
    sourcesTitle: 'text-base font-semibold',
    sourcesList: 'space-y-1 text-sm text-muted',
    sourceOrganization: 'font-medium',
    sourceLink: 'underline',
    gradientWrapper: 'absolute inset-0 overflow-hidden pointer-events-none',
    gradient: 'h-full w-full scale-150 rotate-15',
  },
})

export interface ContentStateProps {
  payload: FactCheckPayload
  hasClaim: boolean
  hasAnalysisSummary: boolean
  hasSources: boolean
  hasVerdict: boolean
  class?: any
  ui?: Partial<typeof contentState.slots>
}

export interface ContentStateEmits {}
export interface ContentStateSlots {}
</script>

<script lang="ts" setup>
const props = defineProps<ContentStateProps>()
defineEmits<ContentStateEmits>()
defineSlots<ContentStateSlots>()

const ui = computed(() => contentState())
</script>

<template>
  <div :class="ui.root({ class: [props.ui?.root, props.class] })">
    <div :class="ui.cardBody({ class: props.ui?.cardBody })">
      <div :class="ui.header({ class: props.ui?.header })">
        <div :class="ui.headerTop({ class: props.ui?.headerTop })">
          <h1 :class="ui.headerTitle({ class: props.ui?.headerTitle })">
            Fact checking
          </h1>

          <UBadge
            v-if="props.hasVerdict"
            color="primary"
            variant="soft"
            size="md"
          >
            {{ props.payload.overall_verdict }}
          </UBadge>
        </div>

        <span :class="ui.poweredBy({ class: props.ui?.poweredBy })">
          powered by <img src="/m-rainbow.svg" :class="ui.logoSmall({ class: props.ui?.logoSmall })">
        </span>
      </div>

      <div :class="ui.content({ class: props.ui?.content })">
        <div v-if="props.hasClaim" :class="ui.section({ class: props.ui?.section })">
          <h2 :class="ui.sectionTitle({ class: props.ui?.sectionTitle })">
            Claim
          </h2>

          <p :class="ui.sectionTextMuted({ class: props.ui?.sectionTextMuted })">
            {{ props.payload.claim.text }}
          </p>
        </div>

        <div v-if="props.hasAnalysisSummary" :class="ui.section({ class: props.ui?.section })">
          <h2 :class="ui.sectionTitle({ class: props.ui?.sectionTitle })">
            Analysis summary
          </h2>

          <p :class="ui.sectionText({ class: props.ui?.sectionText })">
            {{ props.payload.analysis.summary }}
          </p>
        </div>

        <div v-if="props.hasSources" :class="ui.section({ class: props.ui?.section })">
          <h2 :class="ui.sourcesTitle({ class: props.ui?.sourcesTitle })">
            Sources
          </h2>

          <ul :class="ui.sourcesList({ class: props.ui?.sourcesList })">
            <li v-for="(source, index) in props.payload.analysis.sources" :key="`${source.url}-${index}`">
              <span :class="ui.sourceOrganization({ class: props.ui?.sourceOrganization })">{{ source.organization }}</span>
              ·
              <a :href="source.url" target="_blank" rel="noreferrer" :class="ui.sourceLink({ class: props.ui?.sourceLink })">
                {{ source.url }}
              </a>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <div :class="ui.gradientWrapper({ class: props.ui?.gradientWrapper })">
      <Gradient :class="ui.gradient({ class: props.ui?.gradient })" />
    </div>
  </div>
</template>
