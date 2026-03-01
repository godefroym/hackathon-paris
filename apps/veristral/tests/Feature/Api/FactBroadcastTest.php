<?php

use App\Events\FactReceived;
use App\Models\Broadcast;
use Illuminate\Support\Facades\Event;

use function Pest\Laravel\postJson;

it('dispatches the fact received event when a fact is stored', function () {
    Event::fake();

    $broadcast = Broadcast::factory()->create();

    $payload = [
        'broadcast_id' => $broadcast->id,
        'claim' => [
            'text' => 'A claim',
        ],
        'analysis' => [
            'summary' => 'An analysis',
            'sources' => [
                [
                    'organization' => 'INSEE',
                    'url' => 'https://www.insee.fr/fr/statistiques/2381474',
                ],
            ],
        ],
        'overall_verdict' => 'partially_accurate',
    ];

    postJson(route('api.facts.store'), $payload)
        ->assertCreated();

    Event::assertDispatched(FactReceived::class);
});
