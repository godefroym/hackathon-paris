<?php

use App\Models\Fact;
use Inertia\Testing\AssertableInertia;

use function Pest\Laravel\get;
use function Pest\Laravel\withoutVite;

it('lists facts on the home page ordered by created_at descending', function () {
    withoutVite();

    $older = Fact::factory()->create([
        'claim_text' => 'Older fact',
        'created_at' => now()->subMinute(),
    ]);

    $newer = Fact::factory()->create([
        'claim_text' => 'Newer fact',
        'created_at' => now(),
    ]);

    $response = get(route('home'));

    $response
        ->assertSuccessful()
        ->assertInertia(fn (AssertableInertia $page) => $page
            ->component('index')
            ->has('facts', 2)
            ->where('facts.0.id', $newer->id)
            ->where('facts.0.claim.text', 'Newer fact')
            ->where('facts.1.id', $older->id)
            ->where('facts.1.claim.text', 'Older fact')
        );
});
