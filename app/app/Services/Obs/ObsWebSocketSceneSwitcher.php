<?php

namespace App\Services\Obs;

use App\Contracts\ObsSceneSwitcher;
use App\Exceptions\ObsSwitchFailedException;
use InvalidArgumentException;
use SoureCode\OBS\Client;
use Throwable;

class ObsWebSocketSceneSwitcher implements ObsSceneSwitcher
{
    public function switchToScene(string $sceneName): void
    {
        if ($sceneName === '') {
            throw new InvalidArgumentException('The OBS scene name must not be empty.');
        }

        try {
            $client = new Client($this->websocketUrl());
            $client->authenticate((string) config('obs.connection.password'));
            $client->setCurrentProgramScene(sceneName: $sceneName);
        } catch (Throwable $throwable) {
            throw ObsSwitchFailedException::fromThrowable($throwable);
        }
    }

    protected function websocketUrl(): string
    {
        $scheme = (bool) config('obs.connection.secure') ? 'wss' : 'ws';

        return sprintf(
            '%s://%s:%d',
            $scheme,
            (string) config('obs.connection.host'),
            (int) config('obs.connection.port'),
        );
    }
}
