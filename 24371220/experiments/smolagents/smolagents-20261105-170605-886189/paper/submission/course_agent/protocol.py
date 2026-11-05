"""Strict DSML fallback; validated data becomes calls in the official executor."""
import ast
import copy
import json
import math
import re

from .workspace import WorkspaceTools

VERSION = 'dsml-v1'
MARKER = '｜｜DSML｜｜'
OPEN, CLOSE = '<' + MARKER + ' calls>', '</' + MARKER + ' calls>'
INVOKE = re.compile(r'<｜｜DSML｜｜ invoke name="([A-Za-z_][A-Za-z0-9_]*)">')
PARAM = re.compile(r'<｜｜DSML｜｜ parameter name="([A-Za-z_][A-Za-z0-9_]*)" string="(true|false)">')
END_INVOKE, END_PARAM = '</｜｜DSML｜｜ invoke>', '</｜｜DSML｜｜ parameter>'


class ProtocolError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError('duplicate JSON key')
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError('non-finite number')
    if isinstance(value, (list, dict)):
        for item in (value.values() if isinstance(value, dict) else value):
            _finite(item)


def parse_dsml(text):
    if len(text) > 200_000:
        raise ProtocolError('response exceeds adapter limit')
    text = text.strip()
    if not text.startswith(OPEN) or not text.endswith(CLOSE):
        raise ProtocolError('expected one complete DSML calls envelope')
    body = text[len(OPEN):-len(CLOSE)]
    pos, calls = 0, []

    def whitespace():
        nonlocal pos
        while pos < len(body) and body[pos].isspace():
            pos += 1

    while True:
        whitespace()
        if pos == len(body):
            break
        match = INVOKE.match(body, pos)
        if not match:
            raise ProtocolError('invalid invoke or mixed action formats')
        name, pos, arguments = match[1], match.end(), {}
        while True:
            whitespace()
            if body.startswith(END_INVOKE, pos):
                pos += len(END_INVOKE)
                break
            match = PARAM.match(body, pos)
            if not match:
                raise ProtocolError('invalid parameter or incomplete invoke')
            key, string = match.groups()
            if key in arguments:
                raise ProtocolError('duplicate parameter: ' + key)
            start = match.end()
            end = body.find(END_PARAM, start)
            if end < 0:
                raise ProtocolError('unclosed parameter')
            raw = body[start:end]
            if '<' + MARKER in raw or '</' + MARKER in raw:
                raise ProtocolError('nested or ambiguous DSML delimiter')
            try:
                value = raw if string == 'true' else json.loads(raw, object_pairs_hook=_object)
                _finite(value)
            except (ValueError, RecursionError) as exc:
                raise ProtocolError('invalid parameter data: ' + key) from exc
            arguments[key] = value
            pos = end + len(END_PARAM)
        calls.append({'name': name, 'arguments': arguments})
        if len(calls) > 32:
            raise ProtocolError('too many calls')
    if not calls:
        raise ProtocolError('empty calls envelope')
    return calls


def compile_calls(calls, tools):
    # Validate the entire batch before any executable action is returned.
    statements = []
    for index, call in enumerate(calls):
        name, arguments = call['name'], call['arguments']
        if name not in tools:
            raise ProtocolError('unregistered tool: ' + name)
        tool = tools[name]
        schema = getattr(tool, 'parameters', None)
        if schema is None:
            schema = {'type': 'object', 'properties': tool.inputs,
                      'required': [k for k, v in tool.inputs.items() if not v.get('nullable')],
                      'additionalProperties': False}
        try:
            WorkspaceTools._validate_schema_value(arguments, schema)
        except ValueError as exc:
            raise ProtocolError(name + ': ' + str(exc)) from exc
        if name == 'final_answer' and index != len(calls) - 1:
            raise ProtocolError('final_answer must be the last call')
        # repr creates literals; model parameter text is never parsed as code.
        keywords = [ast.keyword(arg=k, value=ast.parse(repr(v), mode='eval').body)
                    for k, v in arguments.items()]
        invocation = ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[], keywords=keywords)
        if name != 'final_answer':
            invocation = ast.Call(func=ast.Name(id='print', ctx=ast.Load()), args=[invocation], keywords=[])
        statements.append(ast.Expr(value=invocation))
    code = ast.unparse(ast.fix_missing_locations(ast.Module(body=statements, type_ignores=[])))
    # These characters occur only in generated literals, never our call syntax.
    # Escape them so a value containing Markdown/XML closing tags cannot end
    # the upstream code-block parser early. Runtime string values stay exact.
    return code.replace('`', r'\x60').replace('<', r'\x3c')


class DSMLAdapter:
    def __init__(self, tools, tags, structured, audit):
        self.tools, self.tags, self.structured, self.audit = tools, tags, structured, audit

    def adapt(self, message):
        raw = message.content
        if not isinstance(raw, str) or MARKER not in raw:
            return message
        # DSML data inside native code/JSON is not a second action.
        if not raw.lstrip().startswith('<' + MARKER):
            outside = re.sub(re.escape(self.tags[0]) + r'.*?' + re.escape(self.tags[1]), '', raw, flags=re.S)
            if self.structured:
                try:
                    json.loads(raw)
                    return message
                except ValueError:
                    pass
            if '<' + MARKER not in outside and '</' + MARKER not in outside:
                return message
        action, calls, error = None, [], None
        try:
            if self.audit.last_classification in {'truncated', 'truncated_empty'}:
                raise ProtocolError('truncated response is not executable')
            if message.tool_calls:
                raise ProtocolError('mixed native tool_calls and DSML')
            calls = parse_dsml(raw)
            action = compile_calls(calls, self.tools)
            content = (json.dumps({'thought': 'DSML adapter-generated action.', 'code': action}, ensure_ascii=False)
                       if self.structured else self.tags[0] + '\n' + action + '\n' + self.tags[1])
        except (ValueError, RecursionError, SyntaxError) as exc:
            error = str(exc)
            # An explicit non-code diagnostic triggers official parsing recovery.
            content = 'DSML_REJECTED: ' + error
        self.audit.log('protocol_adapter', number=self.audit.calls, version=VERSION,
                       protocol='dsml', status='rejected' if error else 'adapted',
                       raw_content=raw, calls=calls, generated_code=action,
                       adapted_content=content, error=error)
        adapted = copy.copy(message)
        adapted.content = content
        return adapted
