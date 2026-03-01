<?php

namespace App\Http\Controllers\Admin;

use App\Http\Controllers\Controller;
use App\Models\Broadcast;
use Illuminate\Http\Request;
use Inertia\Inertia;
use Inertia\Response;

class BroadcastIndexController extends Controller
{
    /**
     * Handle the incoming request.
     */
    public function __invoke(Request $request): Response
    {
        $broadcasts = Broadcast::query()
            ->withCount('facts')
            ->latest()
            ->get()
            ->map(fn (Broadcast $broadcast): array => [
                'id' => $broadcast->id,
                'uuid' => $broadcast->uuid,
                'name' => $broadcast->name,
                'facts_count' => $broadcast->facts_count,
                'closed_at' => $broadcast->closed_at?->toISOString(),
                'summary' => $broadcast->summary,
                'created_at' => $broadcast->created_at?->toISOString(),
            ]);

        return Inertia::render('admin/broadcasts/index', [
            'broadcasts' => $broadcasts,
        ]);
    }
}
