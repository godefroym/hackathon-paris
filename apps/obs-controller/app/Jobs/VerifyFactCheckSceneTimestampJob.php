<?php

namespace App\Jobs;

use App\Contracts\ObsSceneSwitcher;
use App\Events\FactCheckContentUpdated;
use Illuminate\Cache\Repository;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Illuminate\Support\Facades\Cache;

class VerifyFactCheckSceneTimestampJob implements ShouldQueue
{
    use Queueable;

    /**
     * Create a new job instance.
     */
    public function __construct(public int $expectedSwitchAtMs) {}

    /**
     * Execute the job.
     */
    public function handle(ObsSceneSwitcher $obsSceneSwitcher): void
    {
        $latestSwitchAtMs = (int) $this->cache()->get($this->lastSwitchAtCacheKey(), 0);

        if ($latestSwitchAtMs !== $this->expectedSwitchAtMs) {
            return;
        }

        if ($this->elapsedMilliseconds($latestSwitchAtMs) < $this->cooldownMilliseconds()) {
            return;
        }

        $programDefaultScene = (string) config('obs.scenes.program_default');

        $obsSceneSwitcher->switchToScene($programDefaultScene);

        FactCheckContentUpdated::dispatch([
            'claim' => ['text' => ''],
            'analysis' => [
                'summary' => '',
                'sources' => [],
            ],
            'overall_verdict' => '',
        ], $programDefaultScene, now()->getTimestampMs());
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

    protected function elapsedMilliseconds(int $timestampMs): int
    {
        return now()->getTimestampMs() - $timestampMs;
    }

    protected function cooldownMilliseconds(): int
    {
        return (int) config('obs.cooldown_seconds', 5) * 1000;
    }
}
