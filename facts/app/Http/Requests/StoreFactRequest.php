<?php

namespace App\Http\Requests;

use App\Models\Broadcast;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Validator;

class StoreFactRequest extends FormRequest
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
            'broadcast_uuid' => ['required', 'string', 'exists:broadcasts,uuid'],
            'claim' => ['required', 'array'],
            'claim.text' => ['required', 'string'],
            'analysis' => ['required', 'array'],
            'analysis.summary' => ['required', 'string'],
            'analysis.sources' => ['nullable', 'array'],
            'analysis.sources.*.organization' => ['required_with:analysis.sources', 'string'],
            'analysis.sources.*.url' => ['required_with:analysis.sources', 'url'],
            'overall_verdict' => ['required', 'string'],
        ];
    }

    /**
     * Configure additional validation logic after the base rules pass.
     */
    public function after(): array
    {
        return [
            function (Validator $validator): void {
                if ($validator->errors()->has('broadcast_uuid')) {
                    return;
                }

                $broadcast = Broadcast::query()->where('uuid', $this->string('broadcast_uuid'))->first();

                if ($broadcast && $broadcast->isClosed()) {
                    $validator->errors()->add('broadcast_uuid', 'This broadcast is closed and no longer accepts new facts.');
                }
            },
        ];
    }

    /**
     * Get custom messages for validator errors.
     *
     * @return array<string, string>
     */
    public function messages(): array
    {
        return [
            'broadcast_uuid.required' => 'A broadcast UUID is required.',
            'broadcast_uuid.exists' => 'The specified broadcast does not exist.',
            'claim.text.required' => 'The claim text field is required.',
            'analysis.summary.required' => 'The analysis summary field is required.',
            'analysis.sources.*.organization.required_with' => 'Each source requires an organization.',
            'analysis.sources.*.url.required_with' => 'Each source requires a URL.',
        ];
    }
}
