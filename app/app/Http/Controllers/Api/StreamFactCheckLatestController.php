<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Cache\Repository;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Cache;

class StreamFactCheckLatestController extends Controller
{
    public function __invoke(): JsonResponse
    {
        $empty = [
            'claim' => ['text' => ''],
            'analysis' => [
                'summary' => '',
                'sources' => [],
            ],
            'overall_verdict' => '',
            'scene' => '',
            'switched_at_ms' => 0,
            'switched_at' => null,
        ];

        $cached = $this->cache()->get($this->lastPayloadCacheKey());
        if (!is_array($cached)) {
            return response()->json($empty);
        }

        return response()->json([
            'claim' => is_array($cached['claim'] ?? null) ? $cached['claim'] : $empty['claim'],
            'analysis' => is_array($cached['analysis'] ?? null) ? $cached['analysis'] : $empty['analysis'],
            'overall_verdict' => is_string($cached['overall_verdict'] ?? null) ? $cached['overall_verdict'] : '',
            'scene' => is_string($cached['scene'] ?? null) ? $cached['scene'] : '',
            'switched_at_ms' => is_numeric($cached['switched_at_ms'] ?? null) ? (int) $cached['switched_at_ms'] : 0,
            'switched_at' => is_string($cached['switched_at'] ?? null) ? $cached['switched_at'] : null,
        ]);
    }

    protected function cache(): Repository
    {
        $store = config('obs.cache.store');

        if (is_string($store) && $store !== '') {
            return Cache::store($store);
        }

        return Cache::store();
    }

    protected function lastPayloadCacheKey(): string
    {
        return sprintf('%s:last-payload', (string) config('obs.cache.prefix'));
    }
}
