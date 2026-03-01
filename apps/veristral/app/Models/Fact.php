<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class Fact extends Model
{
    /** @use HasFactory<\Database\Factories\FactFactory> */
    use HasFactory;

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'broadcast_id',
        'claim_text',
        'analysis_summary',
        'analysis_sources',
        'overall_verdict',
    ];

    /**
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo<Broadcast, $this>
     */
    public function broadcast(): \Illuminate\Database\Eloquent\Relations\BelongsTo
    {
        return $this->belongsTo(Broadcast::class);
    }

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'analysis_sources' => 'array',
        ];
    }
}
