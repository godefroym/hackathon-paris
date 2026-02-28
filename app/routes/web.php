<?php

use Illuminate\Support\Facades\Route;

Route::inertia('/overlays/fact-check', 'overlays/fact-check/index')
    ->name('overlays.fact-check.index');
