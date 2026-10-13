#!/usr/bin/env python3
"""用最小公开提示检查兼容 Chat Completions 的接入，不读取题目或仓库。"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
from urllib import error, request
from contracts import submission_config_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='读取提交的 config.json；不读取任务或仓库')
    parser.add_argument('--base-url')
    parser.add_argument('--api-model')
    parser.add_argument('--key-env')
    parser.add_argument('--list-models', action='store_true')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--max-tokens', type=int, default=128, help='最小文本检查的输出上限，默认 128')
    parser.add_argument('--thinking', choices=('enabled', 'disabled'),
                        help='仅在服务支持时传入 DeepSeek 格式的思考开关；默认不传')
    args = parser.parse_args(argv)
    if args.max_tokens <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--max-tokens 和 --timeout 必须为正数，--timeout 必须有限')
    config = {}
    if args.config is not None:
        try:
            config = json.loads(args.config.read_text(encoding='utf-8'))
            problem = submission_config_error(config)
            if problem:
                parser.error(f'config.json 配置不合格：{problem}；检查 model、base_url、key_env')
        except (OSError, ValueError):
            parser.error('无法读取 config.json；请检查文件路径与 JSON 格式')
    args.base_url = args.base_url or config.get('base_url') or os.environ.get('COURSE_API_BASE_URL')
    args.api_model = args.api_model or config.get('model') or os.environ.get('COURSE_API_MODEL')
    args.key_env = args.key_env or config.get('key_env') or 'COURSE_API_KEY'
    if not args.base_url:
        parser.error('请用 --config、--base-url 或 COURSE_API_BASE_URL 提供 API 根地址')
    if not args.api_model and not args.list_models:
        parser.error('请用 --config、--api-model 或 COURSE_API_MODEL 提供模型名')
    key = os.environ.get(args.key_env)
    if not key:
        parser.error(f'环境变量 {args.key_env} 未设置')
    base = args.base_url.rstrip('/')
    body = {
        'model': args.api_model, 'messages': [{'role': 'user', 'content': 'Reply OK.'}],
        'max_tokens': args.max_tokens, 'stream': False}
    if args.thinking is not None:
        body['thinking'] = {'type': args.thinking}
    data = None if args.list_models else json.dumps(body).encode()
    try:
        req = request.Request(base + ('/models' if args.list_models else '/chat/completions'), data=data,
                              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with request.urlopen(req, timeout=args.timeout) as response:
            payload = json.load(response)
        if args.list_models:
            print(json.dumps({'model_ids': [m['id'] for m in payload['data']]}, ensure_ascii=False))
        else:
            if not isinstance(payload, dict) or not payload.get('choices'):
                raise ValueError('响应缺少 choices')
            choice = payload['choices'][0]
            content = choice['message']['content']
            if content is not None and not isinstance(content, str):
                raise ValueError('响应 content 不是文本或 null')
            generated = bool(content and content.strip())
            print(json.dumps({'ok': generated, 'request_ok': True, 'text_generated': generated,
                              'requested_model': args.api_model, 'actual_model': payload.get('model'),
                              'content': content, 'finish_reason': choice.get('finish_reason'),
                              'usage': payload.get('usage')}, ensure_ascii=False))
            if not generated:
                print('请求已收到有效响应，但未生成可见文本；检查 finish_reason 和 usage。'
                      '若预算耗尽，可增大 --max-tokens；服务支持时可用 --thinking disabled。', file=sys.stderr)
                return 1
        return 0
    except error.HTTPError as exc:
        print(f'接入失败：HTTP {exc.code}；检查地址、鉴权、模型 ID 和余额。', file=sys.stderr)
    except TimeoutError:
        print('接入失败：连接超时；检查网络/代理，或增大 --timeout。', file=sys.stderr)
    except error.URLError:
        print('接入失败：网络或代理错误；检查连接、DNS、代理和 API 根地址。', file=sys.stderr)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print('接入失败：返回体不是可解析的 JSON；检查 API 根地址与代理返回内容。', file=sys.stderr)
    except (ValueError, KeyError, TypeError, IndexError):
        print('接入失败：响应格式不符合 Chat Completions；检查接口类型与模型 ID。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
