<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class Broadcast extends Model
{
    /** @use HasFactory<\Database\Factories\BroadcastFactory> */
    use HasFactory;

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'name',
        'uuid',
        'closed_at',
        'summary',
    ];

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'closed_at' => 'datetime',
        ];
    }

    public function isClosed(): bool
    {
        return $this->closed_at !== null;
    }

    /**
     * @return \Illuminate\Database\Eloquent\Relations\HasMany<Fact, $this>
     */
    public function facts(): \Illuminate\Database\Eloquent\Relations\HasMany
    {
        return $this->hasMany(Fact::class);
    }
}
