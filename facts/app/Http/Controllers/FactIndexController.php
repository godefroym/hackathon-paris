<?php

namespace App\Http\Controllers;

use App\Models\Fact;
use Illuminate\Http\Request;
use Inertia\Inertia;
use Inertia\Response;

class FactIndexController extends Controller
{
    /**
     * Handle the incoming request.
     */
    public function __invoke(Request $request): Response
    {
        $facts = Fact::query()
            ->with('broadcast:id,name,closed_at')
            ->latest('created_at')
            ->latest('id')
            ->get()
            ->map(fn (Fact $fact): array => [
                'id' => $fact->id,
                'broadcast' => [
                    'id' => $fact->broadcast->id,
                    'name' => $fact->broadcast->name,
                    'closed_at' => $fact->broadcast->closed_at?->toISOString(),
                ],
                'claim' => [
                    'text' => $fact->claim_text,
                ],
                'analysis' => [
                    'summary' => $fact->analysis_summary,
                    'sources' => $fact->analysis_sources ?? [],
                ],
                'overall_verdict' => $fact->overall_verdict,
                'created_at' => $fact->created_at?->toISOString(),
            ]);

        return Inertia::render('index', [
            'facts' => $facts,
        ]);
    }
}
