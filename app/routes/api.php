<?php

use App\Http\Controllers\Api\StreamFactCheckClearController;
use App\Http\Controllers\Api\StreamFactCheckLatestController;
use App\Http\Controllers\Api\StreamFactCheckHistoryController;
use App\Http\Controllers\Api\StreamFactCheckController;
use Illuminate\Support\Facades\Route;

Route::post('/stream/fact-check', StreamFactCheckController::class);
Route::post('/stream/fact-check/clear', StreamFactCheckClearController::class);
Route::get('/stream/fact-check/latest', StreamFactCheckLatestController::class);
Route::get('/stream/fact-check/history', StreamFactCheckHistoryController::class);
