"""Private request snapshots for inspecting inputs, never model reasoning or credentials."""
import json
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / 'data' / 'prompt_requests'
MAX_BYTES = 8 * 1024 * 1024


def model_request(messages, tools=(), parameters=None):
    result = []
    for message in messages:
        if isinstance(message, dict):
            item = {k: message[k] for k in ('role', 'content', 'tool_calls', 'tool_call_id') if k in message}
        else:
            role = {'human': 'user', 'ai': 'assistant'}.get(message.type, message.type)
            item = {'role': role, 'content': message.content}
            if getattr(message, 'tool_calls', None):
                item['tool_calls'] = message.tool_calls
            if getattr(message, 'tool_call_id', None):
                item['tool_call_id'] = message.tool_call_id
        if isinstance(item.get('content'), list):
            item['content'] = [block for block in item['content']
                               if not isinstance(block, dict) or block.get('type') not in
                               {'reasoning', 'thinking', 'redacted_thinking'}]
        result.append(item)
    return {'messages': result, 'tools': [
        {'name': t.name, 'description': t.description,
         'parameters': t.args_schema.model_json_schema() if t.args_schema else {}} for t in tools
    ], 'parameters': parameters or {}}


def save_prompt(conv_id, agent_id, agent_name, kind, request):
    ident = str(uuid.uuid4())
    snapshot = {'conversation_id': str(conv_id), 'agent_id': str(agent_id),
                'agent_name': agent_name, 'kind': kind, 'request': request}
    data = json.dumps(snapshot, ensure_ascii=False, default=str).encode()
    if len(data) > MAX_BYTES:
        raise ValueError('prompt_snapshot_too_large')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ROOT / (ident + '.json')
    with path.open('xb') as handle:
        os.chmod(path, 0o600)
        handle.write(data)
    return {'id': ident, 'kind': kind, 'agent_name': agent_name}


def read_prompt(ident):
    path = ROOT / (str(uuid.UUID(str(ident))) + '.json')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('prompt_snapshot_too_large')
    return json.loads(path.read_bytes())
