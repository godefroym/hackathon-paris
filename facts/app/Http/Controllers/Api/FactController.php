<?php

namespace App\Http\Controllers\Api;

use App\Events\FactReceived;
use App\Http\Controllers\Controller;
use App\Http\Requests\StoreFactRequest;
use App\Models\Broadcast;
use App\Models\Fact;
use Illuminate\Http\JsonResponse;

class FactController extends Controller
{
    /**
     * Store a newly created resource in storage.
     */
    public function store(StoreFactRequest $request): JsonResponse
    {
        $broadcast = Broadcast::query()->where('uuid', $request->string('broadcast_uuid'))->firstOrFail();

        $fact = Fact::query()->create([
            'broadcast_id' => $broadcast->id,
            'claim_text' => $request->string('claim.text')->toString(),
            'analysis_summary' => $request->string('analysis.summary')->toString(),
            'analysis_sources' => $request->input('analysis.sources'),
            'overall_verdict' => $request->string('overall_verdict')->toString(),
        ]);

        event(new FactReceived($fact));

        return response()->json([
            'data' => [
                'id' => $fact->id,
                'broadcast_id' => $fact->broadcast_id,
                'claim' => [
                    'text' => $fact->claim_text,
                ],
                'analysis' => [
                    'summary' => $fact->analysis_summary,
                    'sources' => $fact->analysis_sources ?? [],
                ],
                'overall_verdict' => $fact->overall_verdict,
            ],
        ], 201);
    }
}
