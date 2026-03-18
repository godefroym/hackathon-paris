<?php

use App\Contracts\ObsSceneSwitcher;
use App\Events\FactCheckContentUpdated;
use App\Exceptions\ObsSwitchFailedException;
use App\Jobs\VerifyFactCheckSceneTimestampJob;
use Carbon\CarbonImmutable;
use Illuminate\Support\Facades\Bus;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Event;

it('validates content payload', function () {
    $this->postJson('/api/stream/fact-check', [])
        ->assertUnprocessable()
        ->assertJsonValidationErrors(['claim', 'analysis', 'overall_verdict']);

    $this->postJson('/api/stream/fact-check', [
        'claim' => ['text' => 123],
        'analysis' => ['summary' => 123, 'sources' => [['organization' => [], 'url' => 'not-a-url']]],
        'overall_verdict' => 123,
    ])
        ->assertUnprocessable()
        ->assertJsonValidationErrors([
            'claim.text',
            'analysis.summary',
            'analysis.sources.0.organization',
            'analysis.sources.0.url',
            'overall_verdict',
        ]);
});

it('switches scene, broadcasts content, caches timestamp and dispatches delayed job', function () {
    CarbonImmutable::setTestNow(CarbonImmutable::parse('2026-02-28 12:00:00 UTC'));

    config()->set('obs.scenes.fact_check', 'fact-check');
    config()->set('obs.scenes.program_default', 'program-default');
    config()->set('obs.cache.prefix', 'obs:test');
    config()->set('obs.cooldown_seconds', 5);
    config()->set('obs.persist_fact_check_scene', false);

    Event::fake([FactCheckContentUpdated::class]);
    Bus::fake();

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldReceive('switchToScene')
        ->once()
        ->with('fact-check');

    $this->app->instance(ObsSceneSwitcher::class, $obsSceneSwitcher);

    $response = $this->postJson('/api/stream/fact-check', [
        'claim' => [
            'text' => 'Les affirmations sur l\'intelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires. Elles relèvent davantage de l\'opinion personnelle.',
        ],
        'analysis' => [
            'summary' => 'La population française est d\'environ 67,4 millions, donc 66 millions est une approximation raisonnable. Le chiffre est légèrement inférieur à la réalité mais reste proche.',
            'sources' => [
                [
                    'organization' => 'INSEE',
                    'url' => 'https://www.insee.fr/fr/statistiques/2381474',
                ],
            ],
        ],
        'overall_verdict' => 'partially_accurate',
    ]);

    $response
        ->assertSuccessful()
        ->assertJsonPath('ok', true)
        ->assertJsonPath('scene', 'fact-check')
        ->assertJsonPath('claim.text', 'Les affirmations sur l\'intelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires. Elles relèvent davantage de l\'opinion personnelle.')
        ->assertJsonPath('analysis.summary', 'La population française est d\'environ 67,4 millions, donc 66 millions est une approximation raisonnable. Le chiffre est légèrement inférieur à la réalité mais reste proche.')
        ->assertJsonPath('analysis.sources.0.organization', 'INSEE')
        ->assertJsonPath('analysis.sources.0.url', 'https://www.insee.fr/fr/statistiques/2381474')
        ->assertJsonPath('overall_verdict', 'partially_accurate');

    $cachedTimestamp = Cache::get('obs:test:last-switch-at-ms');

    expect($cachedTimestamp)->toBeInt();

    Event::assertDispatched(FactCheckContentUpdated::class, function (FactCheckContentUpdated $event) use ($cachedTimestamp): bool {
        return $event->factCheck['claim']['text'] === 'Les affirmations sur l\'intelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires. Elles relèvent davantage de l\'opinion personnelle.'
            && $event->factCheck['analysis']['summary'] === 'La population française est d\'environ 67,4 millions, donc 66 millions est une approximation raisonnable. Le chiffre est légèrement inférieur à la réalité mais reste proche.'
            && $event->factCheck['analysis']['sources'][0]['organization'] === 'INSEE'
            && $event->factCheck['analysis']['sources'][0]['url'] === 'https://www.insee.fr/fr/statistiques/2381474'
            && $event->factCheck['overall_verdict'] === 'partially_accurate'
            && $event->scene === 'fact-check'
            && $event->switchedAtMs === $cachedTimestamp;
    });

    Bus::assertDispatched(VerifyFactCheckSceneTimestampJob::class, function (VerifyFactCheckSceneTimestampJob $job) use ($cachedTimestamp): bool {
        return $job->expectedSwitchAtMs === $cachedTimestamp;
    });
});

it('keeps the fact-check scene persistent when configured', function () {
    CarbonImmutable::setTestNow(CarbonImmutable::parse('2026-02-28 12:00:00 UTC'));

    config()->set('obs.scenes.fact_check', 'fact-check');
    config()->set('obs.cache.prefix', 'obs:test');
    config()->set('obs.persist_fact_check_scene', true);

    Event::fake([FactCheckContentUpdated::class]);
    Bus::fake();

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldReceive('switchToScene')
        ->once()
        ->with('fact-check');

    $this->app->instance(ObsSceneSwitcher::class, $obsSceneSwitcher);

    $this->postJson('/api/stream/fact-check', [
        'claim' => ['text' => 'The Earth has 3 billion people.'],
        'analysis' => [
            'summary' => 'The world population is above 8 billion.',
            'sources' => [
                [
                    'organization' => 'World Bank',
                    'url' => 'https://data.worldbank.org/indicator/SP.POP.TOTL',
                ],
            ],
        ],
        'overall_verdict' => 'inaccurate',
    ])->assertSuccessful();

    Bus::assertNotDispatched(VerifyFactCheckSceneTimestampJob::class);
});

it('returns an api error when obs switch fails', function () {
    Event::fake([FactCheckContentUpdated::class]);
    Bus::fake();

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldReceive('switchToScene')
        ->once()
        ->andThrow(new ObsSwitchFailedException('Failed to switch OBS scene.'));

    $this->app->instance(ObsSceneSwitcher::class, $obsSceneSwitcher);

    $this->postJson('/api/stream/fact-check', [
        'claim' => ['text' => 'Payload'],
        'analysis' => [
            'summary' => 'Payload summary',
            'sources' => [
                [
                    'organization' => 'INSEE',
                    'url' => 'https://www.insee.fr/fr/statistiques/2381474',
                ],
            ],
        ],
        'overall_verdict' => 'partially_accurate',
    ])
        ->assertStatus(502)
        ->assertJsonPath('code', 'obs_switch_failed');

    Event::assertNotDispatched(FactCheckContentUpdated::class);
    Bus::assertNotDispatched(VerifyFactCheckSceneTimestampJob::class);
});

afterEach(function () {
    CarbonImmutable::setTestNow();
});
