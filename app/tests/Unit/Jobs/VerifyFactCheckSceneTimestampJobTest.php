<?php

use App\Contracts\ObsSceneSwitcher;
use App\Events\FactCheckContentUpdated;
use App\Jobs\VerifyFactCheckSceneTimestampJob;
use Carbon\CarbonImmutable;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Event;

uses(Tests\TestCase::class);

it('switches back to default scene when timestamp is unchanged after cooldown', function () {
    $expectedSwitchAtMs = 1_772_280_000_000;

    CarbonImmutable::setTestNow(CarbonImmutable::createFromTimestampMs($expectedSwitchAtMs + 5_000));

    config()->set('obs.cache.prefix', 'obs:test');
    config()->set('obs.cooldown_seconds', 5);
    config()->set('obs.scenes.program_default', 'program-default');

    Event::fake([FactCheckContentUpdated::class]);

    Cache::put('obs:test:last-switch-at-ms', $expectedSwitchAtMs, now()->addMinutes(10));

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldReceive('switchToScene')
        ->once()
        ->with('program-default');

    (new VerifyFactCheckSceneTimestampJob($expectedSwitchAtMs))->handle($obsSceneSwitcher);

    Event::assertDispatched(FactCheckContentUpdated::class, function (FactCheckContentUpdated $event): bool {
        return $event->factCheck['claim']['text'] === ''
            && $event->factCheck['analysis']['summary'] === ''
            && $event->factCheck['analysis']['sources'] === []
            && $event->factCheck['overall_verdict'] === ''
            && $event->scene === 'program-default';
    });
});

it('does not switch back when a newer timestamp is stored in cache', function () {
    $expectedSwitchAtMs = 1_772_280_000_000;

    CarbonImmutable::setTestNow(CarbonImmutable::createFromTimestampMs($expectedSwitchAtMs + 5_000));

    config()->set('obs.cache.prefix', 'obs:test');
    config()->set('obs.cooldown_seconds', 5);

    Event::fake([FactCheckContentUpdated::class]);

    Cache::put('obs:test:last-switch-at-ms', $expectedSwitchAtMs + 1_000, now()->addMinutes(10));

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldNotReceive('switchToScene');

    (new VerifyFactCheckSceneTimestampJob($expectedSwitchAtMs))->handle($obsSceneSwitcher);

    Event::assertNotDispatched(FactCheckContentUpdated::class);
});

it('does not switch back before cooldown elapses', function () {
    $expectedSwitchAtMs = 1_772_280_000_000;

    CarbonImmutable::setTestNow(CarbonImmutable::createFromTimestampMs($expectedSwitchAtMs + 4_000));

    config()->set('obs.cache.prefix', 'obs:test');
    config()->set('obs.cooldown_seconds', 5);

    Event::fake([FactCheckContentUpdated::class]);

    Cache::put('obs:test:last-switch-at-ms', $expectedSwitchAtMs, now()->addMinutes(10));

    $obsSceneSwitcher = \Mockery::mock(ObsSceneSwitcher::class);
    $obsSceneSwitcher
        ->shouldNotReceive('switchToScene');

    (new VerifyFactCheckSceneTimestampJob($expectedSwitchAtMs))->handle($obsSceneSwitcher);

    Event::assertNotDispatched(FactCheckContentUpdated::class);
});

afterEach(function () {
    CarbonImmutable::setTestNow();
});
