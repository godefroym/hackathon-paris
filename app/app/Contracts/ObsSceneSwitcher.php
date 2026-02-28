<?php

namespace App\Contracts;

interface ObsSceneSwitcher
{
    public function switchToScene(string $sceneName): void;
}
