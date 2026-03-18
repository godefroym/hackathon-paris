<?php

use Illuminate\Support\Facades\Route;

Route::inertia('/overlays/fact-check', 'overlays/fact-check/index')
    ->name('overlays.fact-check.index');

Route::inertia('/overlays/fact-check-2', 'overlays/fact-check/index')
    ->name('overlays.fact-check.v2');

Route::inertia('/overlays/fact-check-classic', 'overlays/fact-check/classic')
    ->name('overlays.fact-check.classic');

Route::inertia('/overlays/fact-check-monitor', 'overlays/fact-check/monitor')
    ->name('overlays.fact-check.monitor');

Route::inertia('/overlays/fact-check-monitor-scene', 'overlays/fact-check/monitor-scene')
    ->name('overlays.fact-check.monitor-scene');
