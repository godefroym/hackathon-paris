<?php

use App\Models\Broadcast;

use function Pest\Laravel\assertDatabaseCount;
use function Pest\Laravel\assertDatabaseHas;
use function Pest\Laravel\post;
use function Pest\Laravel\withoutVite;

it('creates a broadcast and redirects to the index', function () {
    $response = post(route('admin.broadcasts.store'), [
        'name' => 'Interview BFM TV – 28 Feb 2026',
    ]);

    $response->assertRedirect(route('admin.broadcasts.index'));

    assertDatabaseCount('broadcasts', 1);
    assertDatabaseHas('broadcasts', [
        'name' => 'Interview BFM TV – 28 Feb 2026',
    ]);
});

it('validates that name is required', function () {
    $response = post(route('admin.broadcasts.store'), []);

    $response->assertSessionHasErrors(['name']);

    assertDatabaseCount('broadcasts', 0);
});

it('lists broadcasts on the index page', function () {
    withoutVite();

    $broadcast = Broadcast::factory()->create(['name' => 'Press Conference']);

    $response = $this->get(route('admin.broadcasts.index'));

    $response
        ->assertSuccessful()
        ->assertInertia(fn (\Inertia\Testing\AssertableInertia $page) => $page
            ->component('admin/broadcasts/index')
            ->has('broadcasts', 1)
            ->where('broadcasts.0.id', $broadcast->id)
            ->where('broadcasts.0.name', 'Press Conference')
        );
});
