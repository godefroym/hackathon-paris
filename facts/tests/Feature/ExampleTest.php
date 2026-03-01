<?php

use function Pest\Laravel\withoutVite;

test('returns a successful response', function () {
    withoutVite();

    $response = $this->get(route('home'));

    $response->assertOk();
});
