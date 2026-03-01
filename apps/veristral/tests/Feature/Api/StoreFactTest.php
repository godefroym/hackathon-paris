<?php

use App\Models\Broadcast;
use App\Models\Fact;

use function Pest\Laravel\assertDatabaseCount;
use function Pest\Laravel\assertDatabaseHas;
use function Pest\Laravel\postJson;

it('stores a fact from the expected payload', function () {
    $broadcast = Broadcast::factory()->create();

    $payload = [
        'broadcast_id' => $broadcast->id,
        'claim' => [
            'text' => "Les affirmations sur l'intelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires.",
        ],
        'analysis' => [
            'summary' => "La population française est d'environ 67,4 millions, donc 66 millions est une approximation raisonnable.",
            'sources' => [
                [
                    'organization' => 'INSEE',
                    'url' => 'https://www.insee.fr/fr/statistiques/2381474',
                ],
            ],
        ],
        'overall_verdict' => 'partially_accurate',
    ];

    $response = postJson(route('api.facts.store'), $payload);

    $response
        ->assertCreated()
        ->assertJsonPath('data.claim.text', $payload['claim']['text'])
        ->assertJsonPath('data.analysis.summary', $payload['analysis']['summary'])
        ->assertJsonPath('data.analysis.sources.0.organization', 'INSEE')
        ->assertJsonPath('data.overall_verdict', 'partially_accurate');

    assertDatabaseCount('facts', 1);
    $fact = Fact::query()->firstOrFail();

    expect($fact->broadcast_id)->toBe($broadcast->id)
        ->and($fact->claim_text)->toBe($payload['claim']['text'])
        ->and($fact->analysis_summary)->toBe($payload['analysis']['summary'])
        ->and($fact->analysis_sources)->toBe($payload['analysis']['sources'])
        ->and($fact->overall_verdict)->toBe('partially_accurate');
});

it('accepts payload without sources', function () {
    $broadcast = Broadcast::factory()->create();

    $payload = [
        'broadcast_id' => $broadcast->id,
        'claim' => [
            'text' => 'Fact without source list.',
        ],
        'analysis' => [
            'summary' => 'Summary without sources is still allowed.',
        ],
        'overall_verdict' => 'unverified',
    ];

    $response = postJson(route('api.facts.store'), $payload);

    $response
        ->assertCreated()
        ->assertJsonPath('data.analysis.sources', []);

    assertDatabaseHas('facts', [
        'claim_text' => 'Fact without source list.',
        'overall_verdict' => 'unverified',
    ]);
});

it('validates required nested fields', function () {
    $response = postJson(route('api.facts.store'), []);

    $response
        ->assertUnprocessable()
        ->assertJsonValidationErrors([
            'broadcast_id',
            'claim',
            'analysis',
            'overall_verdict',
        ]);
});
