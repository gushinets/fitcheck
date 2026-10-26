import ast
from pathlib import Path

ROOT=Path(__file__).parents[2]/'src/fitcheck_backend'
BOUNDARIES={'litellm':'llm/litellm_adapter.py','openai':'llm/litellm_adapter.py',
    'pydantic_ai':'llm/structured.py'}


def violations(root):
    result=[]
    for path in root.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [entry.name for entry in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            for name in names:
                boundary=BOUNDARIES.get(name.split('.')[0])
                if boundary and str(path.relative_to(root)) != boundary:
                    result.append((str(path.relative_to(root)),node.lineno,name))
    return result


def test_provider_imports_stay_at_gateway_boundary():
    assert violations(ROOT)==[]


def test_guard_rejects_provider_import_in_product_module(tmp_path):
    (tmp_path/'product.py').write_text('from litellm import acompletion\n')
    assert violations(tmp_path)==[('product.py',1,'litellm')]
