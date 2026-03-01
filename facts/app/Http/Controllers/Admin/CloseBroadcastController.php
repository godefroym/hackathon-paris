<?php

namespace App\Http\Controllers\Admin;

use App\Http\Controllers\Controller;
use App\Models\Broadcast;
use App\Services\MistralService;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;

class CloseBroadcastController extends Controller
{
    public function __construct(private readonly MistralService $mistral) {}

    /**
     * Handle the incoming request.
     */
    public function __invoke(Request $request, Broadcast $broadcast): RedirectResponse
    {
        if ($broadcast->isClosed()) {
            return redirect()->route('admin.broadcasts.index');
        }

        $broadcast->update(['closed_at' => now()]);

        $facts = $broadcast->facts()->get(['claim_text', 'analysis_summary', 'overall_verdict']);

        if ($facts->isNotEmpty()) {
            $summary = $this->mistral->synthesizeBroadcast($broadcast->name, $facts);
            $broadcast->update(['summary' => $summary]);
        }

        return redirect()->route('admin.broadcasts.index');
    }
}
