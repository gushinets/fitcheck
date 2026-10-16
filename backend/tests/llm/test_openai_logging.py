"""Exercise import-time SDK logging in a fresh interpreter, without network access."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize('status', [200, 503])
def test_installed_sdk_debug_logs_never_expose_provider_payloads(status):
    script = textwrap.dedent('''
        import asyncio
        import io
        import json
        import logging
        import socket
        import sys

        stream = io.StringIO()
        logging.basicConfig(stream=stream, level=logging.INFO)
        # A child can have its own level/handler; disabling only its parent
        # neither filters these records nor stops their propagation.
        child = logging.getLogger('openai._base_client')
        child.setLevel(logging.DEBUG)
        child.addHandler(logging.StreamHandler(stream))

        def no_network(*args, **kwargs):
            raise AssertionError('Only MockTransport may send')
        socket.socket.connect = no_network
        socket.socket.connect_ex = no_network

        import httpx
        from fitcheck_backend.llm.errors import ProviderFailure
        from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
        from fitcheck_backend.llm.policy import analysis_policy

        markers = {
            'prompt': 'private-prompt-logging-sentinel',
            'output': 'private-output-logging-sentinel',
            'error': 'raw-provider-error-logging-sentinel',
            'key': 'fake-key-logging-sentinel',
        }
        status = int(sys.argv[1])
        sends = []
        def handle(request):
            sends.append(request)
            assert json.loads(request.content)['messages'][0]['content'] == markers['prompt']
            assert request.headers['authorization'] == 'Bearer ' + markers['key']
            if status != 200:
                return httpx.Response(status, json={'error': {
                    'message': ' '.join(markers.values()), 'type': 'server_error'}})
            return httpx.Response(200, json={
                'id': 'mock-only', 'object': 'chat.completion', 'created': 1,
                'model': 'gpt-6-luna', 'choices': [{'index': 0,
                    'message': {'role': 'assistant', 'content': markers['output']},
                    'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

        async def run():
            adapter = LiteLlmAdapter(markers['key'], transport=httpx.MockTransport(handle))
            try:
                try:
                    reply = await adapter.complete(
                        messages=[{'role': 'user', 'content': markers['prompt']}],
                        policy=analysis_policy(), max_tokens=1200, timeout=2)
                except ProviderFailure as exc:
                    assert status == 503 and exc.code == 'upstream'
                else:
                    assert status == 200 and reply.content == markers['output']
            finally:
                await adapter.aclose()

        asyncio.run(run())
        sdk_logs = stream.getvalue()
        # Future SDK children must also stop at the SDK logging boundary.
        late_child = logging.getLogger('openai.future.child')
        late_child.setLevel(logging.DEBUG)
        late_child.warning(' '.join(markers.values()))
        logging.getLogger('fitcheck.worker').info('operational-health-preserved')
        logging.getLogger('fitcheck.worker').error('operational-failure-preserved')
        logs = stream.getvalue()
        print(json.dumps({
            'sends': len(sends),
            'sdk_leaked': {name: value in sdk_logs for name, value in markers.items()},
            'hierarchy_leaked': {name: value in logs for name, value in markers.items()},
            'health_logged': 'operational-health-preserved' in logs,
            'failure_logged': 'operational-failure-preserved' in logs,
        }))
    ''')
    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-c', script, str(status)],
        cwd=backend, env={'OPENAI_LOG': 'debug', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
            'PYTHONPATH': str(backend / 'src')},
        capture_output=True, text=True, timeout=30)
    # Keep even fake private payloads out of pytest failure diagnostics.
    assert result.returncode == 0, 'Mock-only SDK subprocess failed'
    summary = json.loads(result.stdout)
    assert summary['sends'] == 1
    assert summary['health_logged'] and summary['failure_logged']
    assert not any(summary['sdk_leaked'].values()), summary['sdk_leaked']
    assert not any(summary['hierarchy_leaked'].values()), summary['hierarchy_leaked']
    assert not result.stderr, 'SDK subprocess wrote unexpected stderr'
