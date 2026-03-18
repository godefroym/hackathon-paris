<?php

namespace App\Http\Controllers\Api;

use App\Contracts\ObsSceneSwitcher;
use App\Events\FactCheckContentUpdated;
use App\Http\Controllers\Controller;
use App\Http\Requests\StreamFactCheckRequest;
use App\Jobs\VerifyFactCheckSceneTimestampJob;
use App\Services\FactCheckPayloadCache;
use Illuminate\Http\JsonResponse;

class StreamFactCheckController extends Controller
{
    public function __invoke(
        StreamFactCheckRequest $request,
        ObsSceneSwitcher $obsSceneSwitcher,
        FactCheckPayloadCache $factCheckPayloadCache,
    ): JsonResponse
    {
        /** @var array{claim: array{text: string}, analysis: array{summary: string, sources: array<int, array{organization: string, url: string}>}, overall_verdict: string} $factCheck */
        $factCheck = $request->validated();
        $scene = (string) config('obs.scenes.fact_check');
        $switchedAtMs = now()->getTimestampMs();
        $payload = [
            'claim' => $factCheck['claim'],
            'analysis' => $factCheck['analysis'],
            'overall_verdict' => $factCheck['overall_verdict'],
            'scene' => $scene,
            'switched_at_ms' => $switchedAtMs,
            'switched_at' => now()->toIso8601String(),
            'clear' => false,
        ];

        $obsSceneSwitcher->switchToScene($scene);

        $factCheckPayloadCache->rememberLastSwitchAt($switchedAtMs);
        $factCheckPayloadCache->setLatest($payload);
        $factCheckPayloadCache->appendHistory($payload);

        FactCheckContentUpdated::dispatch($factCheck, $scene, $switchedAtMs);

        if (!config('obs.persist_fact_check_scene', true)) {
            VerifyFactCheckSceneTimestampJob::dispatch($switchedAtMs)
                ->delay(now()->addSeconds((int) config('obs.cooldown_seconds', 5)));
        }

        return response()->json([
            'ok' => true,
            'claim' => $factCheck['claim'],
            'analysis' => $factCheck['analysis'],
            'overall_verdict' => $factCheck['overall_verdict'],
            'scene' => $scene,
            'switched_at_ms' => $switchedAtMs,
        ]);
    }
}
