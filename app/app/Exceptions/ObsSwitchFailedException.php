<?php

namespace App\Exceptions;

use RuntimeException;
use Throwable;

class ObsSwitchFailedException extends RuntimeException
{
    public static function fromThrowable(Throwable $throwable): self
    {
        return new self('Failed to switch OBS scene.', previous: $throwable);
    }
}
