<?php

namespace App\Services;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Http;

class MistralService
{
    private string $baseUrl;

    private string $model;

    public function __construct()
    {
        $this->baseUrl = config('mistral.base_url');
        $this->model = config('mistral.model');
    }

    /**
     * Generate a TL;DR synthesis for a broadcast based on all its fact-checks.
     *
     * @param  Collection<int, array{
     *     claim_text: string,
     *     analysis_summary: string,
     *     overall_verdict: string,
     * }>  $facts
     *
     * @throws ConnectionException
     */
    public function synthesizeBroadcast(string $broadcastName, Collection $facts): string
    {
        $factsBlock = $facts->map(function (array $fact, int $index): string {
            $num = $index + 1;

            return "[{$num}] Claim: {$fact['claim_text']}\n     Verdict: {$fact['overall_verdict']}\n     Analysis: {$fact['analysis_summary']}";
        })->implode("\n\n");

        $totalFacts = $facts->count();
        $falseCount = $facts->filter(fn (array $f): bool => str_contains(strtolower($f['overall_verdict']), 'false')
            || str_contains(strtolower($f['overall_verdict']), 'lie')
            || str_contains(strtolower($f['overall_verdict']), 'misleading')
        )->count();

        $systemPrompt = implode("\n", [
            'You are an expert fact-checker and political analyst. Your role is to produce a concise, frank,',
            'and evidence-based TL;DR synthesis after a live broadcast has been fact-checked in real time.',
            '',
            'Your output must:',
            '- Start with a single overall verdict sentence: was the interviewee generally honest, partially honest, or largely dishonest?',
            '- Highlight the 2-3 most important false or misleading claims with a brief explanation of why they are wrong.',
            '- Highlight any claims that were verified as true and worth noting.',
            '- End with a short "Points to Emphasize" bullet list (3-5 items) for journalists or the public to remember.',
            '- Be written in the same language as the claims (detect it automatically).',
            '- Be factual, neutral, and avoid partisan language.',
            '- Be concise: aim for 200-350 words maximum.',
        ]);

        $userPrompt = implode("\n", [
            "Broadcast: \"{$broadcastName}\"",
            "Total claims fact-checked: {$totalFacts}",
            "Claims flagged as false/misleading: {$falseCount}",
            '',
            'Here are all the fact-checked claims from this broadcast:',
            '',
            $factsBlock,
            '',
            'Please produce the TL;DR synthesis as described.',
        ]);

        $response = Http::withToken(config('mistral.api_key'))
            ->baseUrl($this->baseUrl)
            ->post('/chat/completions', [
                'model' => $this->model,
                'messages' => [
                    ['role' => 'system', 'content' => $systemPrompt],
                    ['role' => 'user', 'content' => $userPrompt],
                ],
            ]);

        $response->throw();

        return $response->json('choices.0.message.content', '');
    }
}
