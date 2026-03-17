<?php

namespace App\Http\Controllers\Api;

use App\Contracts\ObsSceneSwitcher;
use App\Events\FactCheckContentUpdated;
use App\Http\Controllers\Controller;
use App\Http\Requests\StreamFactCheckRequest;
use App\Jobs\VerifyFactCheckSceneTimestampJob;
use Illuminate\Cache\Repository;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Cache;

class StreamFactCheckController extends Controller
{
    public function __invoke(StreamFactCheckRequest $request, ObsSceneSwitcher $obsSceneSwitcher): JsonResponse
    {
        /** @var array{claim: array{text: string}, analysis: array{summary: string, sources: array<int, array{organization: string, url: string}>}, overall_verdict: string} $factCheck */
        $factCheck = $request->validated();
        $scene = (string) config('obs.scenes.fact_check');
        $switchedAtMs = now()->getTimestampMs();

        $obsSceneSwitcher->switchToScene($scene);

        $this->cache()->put($this->lastSwitchAtCacheKey(), $switchedAtMs, now()->addMinutes(10));
        $this->cache()->put($this->lastPayloadCacheKey(), [
            'claim' => $factCheck['claim'],
            'analysis' => $factCheck['analysis'],
            'overall_verdict' => $factCheck['overall_verdict'],
            'scene' => $scene,
            'switched_at_ms' => $switchedAtMs,
            'switched_at' => now()->toIso8601String(),
        ], now()->addMinutes(10));

        FactCheckContentUpdated::dispatch($factCheck, $scene, $switchedAtMs);

        VerifyFactCheckSceneTimestampJob::dispatch($switchedAtMs)
            ->delay(now()->addSeconds((int) config('obs.cooldown_seconds', 5)));

        return response()->json([
            'ok' => true,
            'claim' => $factCheck['claim'],
            'analysis' => $factCheck['analysis'],
            'overall_verdict' => $factCheck['overall_verdict'],
            'scene' => $scene,
            'switched_at_ms' => $switchedAtMs,
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

    protected function lastSwitchAtCacheKey(): string
    {
        return sprintf('%s:last-switch-at-ms', (string) config('obs.cache.prefix'));
    }

    protected function lastPayloadCacheKey(): string
    {
        return sprintf('%s:last-payload', (string) config('obs.cache.prefix'));
    }
}
