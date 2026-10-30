"""底层传输、受限工具、真实日志和补丁；仅使用标准库。"""
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


class Runtime:
    def __init__(self, repo, output, editable, config):
        self.repo = Path(repo).resolve(strict=True)
        self.output = Path(output).resolve()
        self.editable = set(editable)
        self.config = config
        self.secret = os.environ.get(config['key_env'], '')
        self.before = {name: self.path(name).read_text(encoding='utf-8')
                       for name in editable}
        for name in ('run.log', 'patch.diff'):
            target = self.output / name
            if target.exists() or target.is_symlink():
                raise ValueError(f'启动目录已有 {name}，请换新目录，避免覆盖历史记录')
        self.logfile = (self.output / 'run.log').open('x', encoding='utf-8')

    def log(self, event, **fields):
        line = json.dumps({'event': event, 'time': time.time(), **fields}, ensure_ascii=False)
        if self.secret:
            line = line.replace(self.secret, '[REDACTED]')
        self.logfile.write(line + '\n')
        self.logfile.flush()

    def path(self, name):
        path = (self.repo / name).resolve()
        if not path.is_relative_to(self.repo) or path == self.repo:
            raise ValueError('文件路径必须在 --repo 内')
        relative = path.relative_to(self.repo)
        if any(part.startswith('.') for part in relative.parts):
            raise ValueError('不能访问隐藏配置或环境文件')
        return path

    def read(self, name):
        content = self.path(name).read_text(encoding='utf-8')
        self.log('file_read', path=name, content=content)
        return {'content': content}

    def write(self, name, content):
        if name not in self.editable or not isinstance(content, str):
            raise ValueError('只能写入题目允许的业务文件，content 必须为字符串')
        self.path(name).write_text(content, encoding='utf-8', newline='')
        self.log('file_write', path=name, content=content)
        return {'written': name}

    def command(self, argv):
        # 不提供 shell、删除、任意脚本或 Python -c，避免操作项目外文件。
        allowed = [['python', '-m', 'pytest', '-q'], ['python', 'run_checks.py']]
        if argv not in allowed:
            raise ValueError('仅允许完整 pytest 和题目自带 run_checks.py')
        actual = [sys.executable, *argv[1:]]
        env = dict(os.environ)
        env.pop(self.config['key_env'], None)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        process = subprocess.Popen(actual, cwd=self.repo, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace',
                                   start_new_session=os.name != 'nt')
        try:
            stdout, stderr = process.communicate(timeout=120)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            if os.name != 'nt':
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            stdout, stderr = process.communicate()
            self.log('command_result', argv=actual, rc=process.returncode,
                     stdout=stdout, stderr=stderr)
            raise exc
        result = {'rc': process.returncode, 'stdout': stdout, 'stderr': stderr}
        self.log('command_result', argv=actual, **result)
        return result

    def request(self, messages):
        if not self.secret:
            raise ValueError(f"未设置环境变量 {self.config['key_env']}")
        body = {'model': self.config['model'], 'messages': messages,
                'stream': False, 'temperature': self.config.get('temperature', 0),
                'response_format': {'type': 'json_object'},
                'max_tokens': self.config.get('max_tokens', 4096)}
        self.log('model_request', body=body)
        url = self.config['base_url'].rstrip('/') + '/chat/completions'
        request = urllib.request.Request(url, json.dumps(body).encode(),
                    {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.secret})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.load(response)
        except Exception as exc:
            # HTTP 正文保留错误信息，不记录请求头。
            detail = exc.read().decode('utf-8', 'replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
            self.log('model_error', error=detail)
            raise RuntimeError('模型接入失败：' + detail) from exc
        self.log('model_response', response=payload)
        self.log('usage', actual_model=payload.get('model', 'unknown'),
                 usage=payload.get('usage', 'unknown'))
        return payload['choices'][0]['message']['content']

    def patch(self):
        chunks = []
        for name, original in self.before.items():
            current = self.path(name).read_text(encoding='utf-8')
            lines = difflib.unified_diff(original.splitlines(True), current.splitlines(True),
                                        fromfile='a/' + name, tofile='b/' + name)
            for line in lines:
                chunks.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
        (self.output / 'patch.diff').write_text(''.join(chunks), encoding='utf-8', newline='')
        self.logfile.close()
