<?php

return [
    'connection' => [
        'host' => env('OBS_HOST', '127.0.0.1'),
        'port' => (int) env('OBS_PORT', 4455),
        'password' => env('OBS_PASSWORD', ''),
        'secure' => (bool) env('OBS_SECURE', false),
    ],

    'scenes' => [
        'fact_check' => env('OBS_SCENE_FACT_CHECK', 'fact-check'),
        'program_default' => env('OBS_SCENE_PROGRAM_DEFAULT', 'program-default'),
    ],

    'cache' => [
        'store' => env('OBS_CACHE_STORE'),
        'prefix' => env('OBS_CACHE_PREFIX', 'obs:fact-check'),
    ],

    'cooldown_seconds' => (int) env('OBS_COOLDOWN_SECONDS', 5),

    'persist_fact_check_scene' => filter_var(
        env('OBS_PERSIST_FACT_CHECK_SCENE', true),
        FILTER_VALIDATE_BOOL,
    ),
];
