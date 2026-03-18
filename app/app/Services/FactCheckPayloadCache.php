<?php

namespace App\Services;

use Illuminate\Cache\Repository;
use Illuminate\Support\Facades\Cache;

class FactCheckPayloadCache
{
    public function getLatest(): array
    {
        $cached = $this->cache()->get($this->lastPayloadCacheKey());

        return is_array($cached) ? $cached : $this->emptyPayload();
    }

    public function setLatest(array $payload): void
    {
        $this->cache()->put($this->lastPayloadCacheKey(), $payload, now()->addMinutes(10));
    }

    public function appendHistory(array $payload, int $limit = 100): void
    {
        $history = $this->getHistory($limit);
        $history[] = $payload;

        if (count($history) > $limit) {
            $history = array_slice($history, -$limit);
        }

        $this->cache()->put($this->historyCacheKey(), array_values($history), now()->addHours(6));
    }

    public function getHistory(int $limit = 100): array
    {
        $history = $this->cache()->get($this->historyCacheKey());
        if (!is_array($history)) {
            return [];
        }

        return array_values(array_slice($history, -$limit));
    }

    public function clearHistory(): void
    {
        $this->cache()->forget($this->historyCacheKey());
    }

    public function forgetLastSwitchAt(): void
    {
        $this->cache()->forget($this->lastSwitchAtCacheKey());
    }

    public function rememberLastSwitchAt(int $switchedAtMs): void
    {
        $this->cache()->put($this->lastSwitchAtCacheKey(), $switchedAtMs, now()->addMinutes(10));
    }

    public function emptyPayload(?int $switchedAtMs = null): array
    {
        $timestampMs = $switchedAtMs ?? now()->getTimestampMs();

        return [
            'claim' => ['text' => ''],
            'analysis' => [
                'summary' => '',
                'sources' => [],
            ],
            'overall_verdict' => '',
            'scene' => '',
            'switched_at_ms' => $timestampMs,
            'switched_at' => now()->toIso8601String(),
            'clear' => false,
        ];
    }

    protected function cache(): Repository
    {
        $store = config('obs.cache.store');

        if (is_string($store) && $store !== '') {
            return Cache::store($store);
        }

        return Cache::store();
    }

    protected function lastSwitchAtCacheKey(): string
    {
        return sprintf('%s:last-switch-at-ms', (string) config('obs.cache.prefix'));
    }

    protected function lastPayloadCacheKey(): string
    {
        return sprintf('%s:last-payload', (string) config('obs.cache.prefix'));
    }

    protected function historyCacheKey(): string
    {
        return sprintf('%s:history', (string) config('obs.cache.prefix'));
    }
}
