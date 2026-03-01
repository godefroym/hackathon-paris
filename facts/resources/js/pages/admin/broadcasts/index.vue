<script setup lang="ts">
import { Head, useForm } from '@inertiajs/vue3';
import { store } from '../../../routes/admin/broadcasts';
import BroadcastItem from './BroadcastItem.vue';

interface Broadcast {
    id: number;
    uuid: string;
    name: string;
    facts_count: number;
    closed_at: string | null;
    summary: string | null;
    created_at: string | null;
}

defineProps<{
    broadcasts: Broadcast[];
}>();

const form = useForm({
    name: '',
});

function submit() {
    form.submit(store(), {
        onSuccess: () => form.reset(),
    });
}
</script>

<template>
    <Head title="Admin – Broadcasts" />

    <main class="mx-auto max-w-3xl px-6 py-10">
        <h1 class="mb-8 text-3xl font-bold">Broadcasts</h1>

        <section class="mb-10">
            <h2 class="mb-4 text-xl font-semibold">New broadcast</h2>
            <form
                class="flex gap-3"
                @submit.prevent="submit"
            >
                <input
                    v-model="form.name"
                    class="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-black"
                    placeholder="e.g. Interview BFM TV – 28 Feb 2026"
                    type="text"
                />
                <button
                    class="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
                    type="submit"
                    :disabled="form.processing"
                >
                    Create
                </button>
            </form>
            <p
                v-if="form.errors.name"
                class="mt-1 text-sm text-red-600"
            >
                {{ form.errors.name }}
            </p>
        </section>

        <section>
            <h2 class="mb-4 text-xl font-semibold">All broadcasts</h2>

            <p
                v-if="broadcasts.length === 0"
                class="text-gray-500"
            >
                No broadcasts yet.
            </p>

            <ul
                v-else
                class="space-y-4"
            >
                <BroadcastItem
                    v-for="broadcast in broadcasts"
                    :key="broadcast.id"
                    :broadcast="broadcast"
                />
            </ul>
        </section>
    </main>
</template>
