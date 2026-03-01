<?php

namespace Database\Factories;

use App\Models\Broadcast;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends \Illuminate\Database\Eloquent\Factories\Factory<\App\Models\Fact>
 */
class FactFactory extends Factory
{
    /**
     * Define the model's default state.
     *
     * @return array<string, mixed>
     */
    public function definition(): array
    {
        return [
            'broadcast_id' => Broadcast::factory(),
            'claim_text' => fake()->sentence(),
            'analysis_summary' => fake()->paragraph(),
            'analysis_sources' => [
                [
                    'organization' => fake()->company(),
                    'url' => fake()->url(),
                ],
            ],
            'overall_verdict' => fake()->randomElement(['accurate', 'inaccurate', 'partially_accurate']),
        ];
    }
}
