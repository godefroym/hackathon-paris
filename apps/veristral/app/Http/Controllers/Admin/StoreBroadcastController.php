<?php

namespace App\Http\Controllers\Admin;

use App\Http\Controllers\Controller;
use App\Http\Requests\StoreBroadcastRequest;
use App\Models\Broadcast;
use Illuminate\Http\RedirectResponse;

class StoreBroadcastController extends Controller
{
    /**
     * Handle the incoming request.
     */
    public function __invoke(StoreBroadcastRequest $request): RedirectResponse
    {
        Broadcast::query()->create([
            'uuid' => str()->uuid()->toString(),
            'name' => $request->string('name')->toString(),
        ]);

        return redirect()->route('admin.broadcasts.index');
    }
}
