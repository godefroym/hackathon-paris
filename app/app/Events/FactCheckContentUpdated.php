<?php

namespace App\Events;

use Carbon\CarbonImmutable;
use Illuminate\Broadcasting\Channel;
use Illuminate\Broadcasting\InteractsWithSockets;
use Illuminate\Contracts\Broadcasting\ShouldBroadcastNow;
use Illuminate\Foundation\Events\Dispatchable;
use Illuminate\Queue\SerializesModels;

class FactCheckContentUpdated implements ShouldBroadcastNow
{
    use Dispatchable, InteractsWithSockets, SerializesModels;

    /**
     * Create a new event instance.
     */
    public function __construct(
        /** @var array{claim: array{text: string}, analysis: array{summary: string, sources: array<int, array{organization: string, url: string}>}, overall_verdict: string} */
        public array $factCheck,
        public string $scene,
        public int $switchedAtMs,
        public bool $clear = false,
    ) {}

    /**
     * Get the channels the event should broadcast on.
     *
     * @return array<int, \Illuminate\Broadcasting\Channel>
     */
    public function broadcastOn(): array
    {
        return [
            new Channel('stream.fact-check'),
        ];
    }

    public function broadcastAs(): string
    {
        return 'stream.fact-check.content-updated';
    }

    /**
     * @return array<string, mixed>
     */
    public function broadcastWith(): array
    {
        return [
            'claim' => $this->factCheck['claim'],
            'analysis' => $this->factCheck['analysis'],
            'overall_verdict' => $this->factCheck['overall_verdict'],
            'scene' => $this->scene,
            'switched_at_ms' => $this->switchedAtMs,
            'switched_at' => CarbonImmutable::createFromTimestampMs($this->switchedAtMs)->toIso8601String(),
            'clear' => $this->clear,
        ];
    }
}
