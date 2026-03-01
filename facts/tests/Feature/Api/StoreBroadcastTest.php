<?php

use App\Models\Broadcast;

use function Pest\Laravel\assertDatabaseCount;
use function Pest\Laravel\postJson;

it('requires a valid broadcast_id when storing a fact', function () {
    $response = postJson(route('api.facts.store'), [
        'claim' => ['text' => 'A claim'],
        'analysis' => ['summary' => 'A summary'],
        'overall_verdict' => 'accurate',
    ]);

    $response
        ->assertUnprocessable()
        ->assertJsonValidationErrors(['broadcast_id']);

    assertDatabaseCount('facts', 0);
});

it('rejects a broadcast_id that does not exist', function () {
    $response = postJson(route('api.facts.store'), [
        'broadcast_id' => 9999,
        'claim' => ['text' => 'A claim'],
        'analysis' => ['summary' => 'A summary'],
        'overall_verdict' => 'accurate',
    ]);

    $response
        ->assertUnprocessable()
        ->assertJsonValidationErrors(['broadcast_id']);

    assertDatabaseCount('facts', 0);
});

it('stores a fact linked to the given broadcast', function () {
    $broadcast = Broadcast::factory()->create();

    $response = postJson(route('api.facts.store'), [
        'broadcast_id' => $broadcast->id,
        'claim' => ['text' => 'A linked claim'],
        'analysis' => ['summary' => 'Analysis here'],
        'overall_verdict' => 'accurate',
    ]);

    $response
        ->assertCreated()
        ->assertJsonPath('data.broadcast_id', $broadcast->id);

    assertDatabaseCount('facts', 1);

    expect($broadcast->facts()->count())->toBe(1);
});
