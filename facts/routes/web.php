<?php

use App\Http\Controllers\Admin\BroadcastIndexController;
use App\Http\Controllers\Admin\CloseBroadcastController;
use App\Http\Controllers\Admin\StoreBroadcastController;
use App\Http\Controllers\FactIndexController;
use Illuminate\Support\Facades\Route;

Route::get('/', FactIndexController::class)->name('home');

Route::prefix('admin')->name('admin.')->group(function () {
    Route::get('/broadcasts', BroadcastIndexController::class)->name('broadcasts.index');
    Route::post('/broadcasts', StoreBroadcastController::class)->name('broadcasts.store');
    Route::post('/broadcasts/{broadcast}/close', CloseBroadcastController::class)->name('broadcasts.close');
});
