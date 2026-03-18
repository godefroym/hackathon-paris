<?php

namespace App\Http\Controllers\Api;

use App\Events\FactCheckContentUpdated;
use App\Http\Controllers\Controller;
use App\Services\FactCheckPayloadCache;
use Illuminate\Http\JsonResponse;

class StreamFactCheckClearController extends Controller
{
    public function __invoke(FactCheckPayloadCache $factCheckPayloadCache): JsonResponse
    {
        $switchedAtMs = now()->getTimestampMs();
        $empty = $factCheckPayloadCache->emptyPayload($switchedAtMs);
        $empty['clear'] = true;

        $factCheckPayloadCache->forgetLastSwitchAt();
        $factCheckPayloadCache->setLatest($empty);
        $factCheckPayloadCache->clearHistory();

        FactCheckContentUpdated::dispatch(
            [
                'claim' => $empty['claim'],
                'analysis' => $empty['analysis'],
                'overall_verdict' => $empty['overall_verdict'],
            ],
            '',
            $switchedAtMs,
            true,
        );

        return response()->json([
            'ok' => true,
            'cleared' => true,
            'switched_at_ms' => $switchedAtMs,
        ]);
    }
}
