<script lang="ts">
const loadingState = tv({
  slots: {
    root: 'text-center',
    logoLarge: 'size-12',
    loadingText: 'mt-2 text-sm text-muted flex items-end gap-1',
    loadingDots: 'flex flex-row items-baseline gap-1 mb-1',
    loadingDot: 'bg-current size-1 rounded-full opacity-30 animate-[dot-hop_2s_ease-in-out_infinite]',
    loadingDotDelayedOne: 'bg-current size-1 rounded-full opacity-30 animate-[dot-hop_2s_ease-in-out_infinite] [animation-delay:0.66s]',
    loadingDotDelayedTwo: 'bg-current size-1 rounded-full opacity-30 animate-[dot-hop_2s_ease-in-out_infinite] [animation-delay:1.32s]',
    gradientWrapper: 'absolute inset-0 pointer-events-none',
    gradient: 'h-full w-full scale-150 rotate-15',
  },
})

export interface LoadingStateProps {
  class?: any
  ui?: Partial<typeof loadingState.slots>
}

export interface LoadingStateEmits {}
export interface LoadingStateSlots {}
</script>

<script lang="ts" setup>
const props = defineProps<LoadingStateProps>()
defineEmits<LoadingStateEmits>()
defineSlots<LoadingStateSlots>()

const ui = computed(() => loadingState())
</script>

<template>
  <div :class="ui.root({ class: [props.ui?.root, props.class] })">
    <img src="/m-rainbow.svg" :class="ui.logoLarge({ class: props.ui?.logoLarge })">

    <div :class="ui.loadingText({ class: props.ui?.loadingText })">
      <span>Analyzing statements</span>
      <span :class="ui.loadingDots({ class: props.ui?.loadingDots })" aria-hidden="true">
        <span :class="ui.loadingDot({ class: props.ui?.loadingDot })" />
        <span :class="ui.loadingDotDelayedOne({ class: props.ui?.loadingDotDelayedOne })" />
        <span :class="ui.loadingDotDelayedTwo({ class: props.ui?.loadingDotDelayedTwo })" />
      </span>
    </div>

    <div :class="ui.gradientWrapper({ class: props.ui?.gradientWrapper })">
      <Gradient :class="ui.gradient({ class: props.ui?.gradient })" />
    </div>
  </div>
</template>
