<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\FactCheckPayloadCache;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class StreamFactCheckHistoryController extends Controller
{
    public function __invoke(Request $request, FactCheckPayloadCache $factCheckPayloadCache): JsonResponse
    {
        $limit = max(1, min((int) $request->integer('limit', 100), 200));

        return response()->json([
            'items' => $factCheckPayloadCache->getHistory($limit),
        ]);
    }
}
