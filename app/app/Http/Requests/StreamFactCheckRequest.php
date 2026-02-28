<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class StreamFactCheckRequest extends FormRequest
{
    /**
     * Determine if the user is authorized to make this request.
     */
    public function authorize(): bool
    {
        return true;
    }

    /**
     * Get the validation rules that apply to the request.
     *
     * @return array<string, \Illuminate\Contracts\Validation\ValidationRule|array<mixed>|string>
     */
    public function rules(): array
    {
        return [
            'claim' => ['required', 'array:text'],
            'claim.text' => ['required', 'string', 'max:2000'],
            'analysis' => ['required', 'array:summary,sources'],
            'analysis.summary' => ['required', 'string', 'max:3000'],
            'analysis.sources' => ['required', 'array', 'min:1'],
            'analysis.sources.*' => ['required', 'array:organization,url'],
            'analysis.sources.*.organization' => ['required', 'string', 'max:255'],
            'analysis.sources.*.url' => ['required', 'url', 'max:2048'],
            'overall_verdict' => ['required', 'string', 'max:100'],
        ];
    }

    /**
     * @return array<string, string>
     */
    public function messages(): array
    {
        return [
            'claim.required' => 'A claim object is required.',
            'claim.array' => 'The claim value must be an object.',
            'claim.text.required' => 'A claim text value is required.',
            'claim.text.string' => 'The claim text value must be a string.',
            'claim.text.max' => 'The claim text value may not exceed :max characters.',
            'analysis.required' => 'An analysis object is required.',
            'analysis.array' => 'The analysis value must be an object.',
            'analysis.summary.required' => 'An analysis summary value is required.',
            'analysis.summary.string' => 'The analysis summary value must be a string.',
            'analysis.summary.max' => 'The analysis summary value may not exceed :max characters.',
            'analysis.sources.required' => 'At least one analysis source is required.',
            'analysis.sources.array' => 'The analysis sources value must be an array.',
            'analysis.sources.min' => 'At least one analysis source is required.',
            'analysis.sources.*.organization.required' => 'A source organization value is required.',
            'analysis.sources.*.organization.string' => 'The source organization value must be a string.',
            'analysis.sources.*.organization.max' => 'The source organization value may not exceed :max characters.',
            'analysis.sources.*.url.required' => 'A source URL value is required.',
            'analysis.sources.*.url.url' => 'The source URL value must be a valid URL.',
            'analysis.sources.*.url.max' => 'The source URL value may not exceed :max characters.',
            'overall_verdict.required' => 'An overall verdict value is required.',
            'overall_verdict.string' => 'The overall verdict value must be a string.',
            'overall_verdict.max' => 'The overall verdict value may not exceed :max characters.',
        ];
    }
}
