"""One bounded, schema-validated tool call, with no credentials in logs."""
import os
from urllib.parse import urlparse
import httpx


def configured():
    return all(os.getenv(k, '').strip() for k in ('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL'))


async def call_tool(name, description, schema, messages, temperature=0):
    base = os.environ['LLM_BASE_URL'].rstrip('/')
    body = {'model': os.environ['LLM_MODEL'], 'temperature': temperature, 'max_tokens': 1600,
            'messages': messages, 'tools': [{'type': 'function', 'function': {
                'name': name, 'description': description, 'parameters': schema.model_json_schema()}}],
            'tool_choice': {'type': 'function', 'function': {'name': name}}}
    if urlparse(base).hostname == 'api.deepseek.com':
        body['thinking'] = {'type': 'disabled'}
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.post(base + '/chat/completions', headers={
            'Authorization': 'Bearer ' + os.environ['LLM_API_KEY']}, json=body)
        response.raise_for_status()
        function = response.json()['choices'][0]['message']['tool_calls'][0]['function']
        if function['name'] != name:
            raise ValueError('Unexpected tool response')
        return schema.model_validate_json(function['arguments'])
