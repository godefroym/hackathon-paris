<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\FactCheckPayloadCache;
use Illuminate\Http\JsonResponse;

class StreamFactCheckLatestController extends Controller
{
    public function __invoke(FactCheckPayloadCache $factCheckPayloadCache): JsonResponse
    {
        $cached = $factCheckPayloadCache->getLatest();
        $empty = $factCheckPayloadCache->emptyPayload(0);
        $empty['switched_at'] = null;

        return response()->json([
            'claim' => is_array($cached['claim'] ?? null) ? $cached['claim'] : $empty['claim'],
            'analysis' => is_array($cached['analysis'] ?? null) ? $cached['analysis'] : $empty['analysis'],
            'overall_verdict' => is_string($cached['overall_verdict'] ?? null) ? $cached['overall_verdict'] : '',
            'scene' => is_string($cached['scene'] ?? null) ? $cached['scene'] : '',
            'switched_at_ms' => is_numeric($cached['switched_at_ms'] ?? null) ? (int) $cached['switched_at_ms'] : 0,
            'switched_at' => is_string($cached['switched_at'] ?? null) ? $cached['switched_at'] : null,
            'clear' => (bool) ($cached['clear'] ?? false),
        ]);
    }
}
