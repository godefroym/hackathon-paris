<?php

use App\Http\Controllers\Api\FactController;
use Illuminate\Support\Facades\Route;

Route::post('/facts', [FactController::class, 'store'])->name('api.facts.store');
