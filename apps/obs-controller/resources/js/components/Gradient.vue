<script lang="ts">
const gradient = tv({
  slots: {
    base: 'opacity-20 grid grid-cols-3 blur-2xl',
    red: 'bg-[#E10500]',
    orange: 'bg-[#FF8205]',
    yellow: 'bg-[#FFD800]',
  },
})

export interface GradientProps {
  class?: any
  ui?: Partial<typeof gradient.slots>
}
export interface GradientEmits {}
export interface GradientSlots {}
</script>

<script lang="ts" setup>
const props = defineProps<GradientProps>()
defineEmits<GradientEmits>()
defineSlots<GradientSlots>()

const ui = computed(() => gradient())
</script>

<template>
    <div :class="ui.base({ class: [props.ui?.base, props.class] })">
        <div :class="ui.red({ class: props.ui?.red })" />
        <div :class="ui.orange({ class: props.ui?.orange })" />
        <div :class="ui.yellow({ class: props.ui?.yellow })" />
    </div>
</template>
