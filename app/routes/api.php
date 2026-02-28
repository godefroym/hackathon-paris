<?php

use App\Http\Controllers\Api\StreamFactCheckController;
use Illuminate\Support\Facades\Route;

Route::post('/stream/fact-check', StreamFactCheckController::class);
