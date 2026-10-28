"""A small AST interpreter with isolated computation and parent-side tool RPC."""
from __future__ import annotations

import ast
import multiprocessing as mp
import queue
import json
import os
import time
import traceback
from typing import Any, Callable


class ParseError(ValueError):
    pass


def parse_code(text: str) -> str:
    """Extract exactly one Python fenced block or one <code> block."""
    import re
    fenced = re.findall(r"```([^\n`]*)\n?(.*?)```", text, re.I | re.S)
    blocks = [body for lang, body in fenced if lang.strip().lower() in ("", "python", "py")]
    html = re.findall(r"<code\b[^>]*>(.*?)</code\s*>", text, re.I | re.S)
    if len(blocks) + len(html) != 1 or len(fenced) + len(html) != 1:
        raise ParseError("expected exactly one fenced Python or <code> block")
    return (blocks + html)[0].strip()


class ExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _ExecutionFinished(Exception):
    """Internal signal: a successful finish tool ends this code block."""


_BIN = {ast.Add: lambda a,b:a+b, ast.Sub:lambda a,b:a-b, ast.Mult:lambda a,b:a*b,
        ast.Div:lambda a,b:a/b, ast.FloorDiv:lambda a,b:a//b, ast.Mod:lambda a,b:a%b,
        ast.Pow:lambda a,b:a**b}
_CMP = {ast.Eq:lambda a,b:a==b, ast.NotEq:lambda a,b:a!=b, ast.Lt:lambda a,b:a<b,
        ast.LtE:lambda a,b:a<=b, ast.Gt:lambda a,b:a>b, ast.GtE:lambda a,b:a>=b,
        ast.In:lambda a,b:a in b, ast.NotIn:lambda a,b:a not in b}
_BUILTINS = {"len":len,"range":range,"enumerate":enumerate,"zip":zip,"sorted":sorted,
 "str":str,"int":int,"float":float,"bool":bool,"list":list,"dict":dict,
 "min":min,"max":max,"sum":sum}
_DEFAULT_TOOLS = {"list_files", "search_code", "read_file", "read_range", "read_symbol", "write_file", "replace_text", "read_pdf", "run_command", "update_plan", "save_note", "get_evidence", "finish", "read", "list", "write", "command", "plan"}
_MAX_VALUE=1_000_000
_MAX_OUTPUT=20000

def _unique_sources(items):
    out=[]; seen=set()
    for item in items:
        key=(item.get("path"),item.get("file_hash"))
        if key not in seen: seen.add(key);out.append(item)
    return out


def _validate(tree: ast.Module, tool_names=_DEFAULT_TOOLS) -> None:
    allowed=(ast.Module,ast.Expr,ast.Assign,ast.AugAssign,ast.Name,ast.Constant,ast.List,ast.Tuple,
      ast.Dict,ast.Subscript,ast.Slice,ast.Load,ast.Store,ast.For,ast.If,ast.Compare,ast.BoolOp,
      ast.And,ast.Or,ast.Not,ast.UnaryOp,ast.USub,ast.UAdd,ast.BinOp,ast.Add,ast.Sub,ast.Mult,
      ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,
      ast.In,ast.NotIn,ast.Call,ast.keyword)
    for n in ast.walk(tree):
        if not isinstance(n,allowed): raise ExecutionError("invalid_ast",f"unsupported syntax: {type(n).__name__}")
        if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and (n.id in _BUILTINS or n.id in tool_names or n.id=="print"):
            raise ExecutionError("invalid_ast",f"reserved name: {n.id}")
        if isinstance(n,ast.Call):
            if isinstance(n.func,ast.Attribute) and n.func.attr=="get":
                raise ExecutionError("invalid_ast","method calls are not supported; use result['key'] instead of result.get('key'); for optional keys, use if 'key' in result")
            if not isinstance(n.func,ast.Name) or (n.func.id not in _BUILTINS and n.func.id not in tool_names and n.func.id!="print"):
                raise ExecutionError("invalid_ast","only registered tools and approved builtins may be called")
            if n.func.id in _BUILTINS or n.func.id=="print":
                if n.keywords: raise ExecutionError("invalid_ast","keyword arguments are not supported for builtins")
            elif n.args:
                example = "get_evidence(evidence_id='...')" if n.func.id=="get_evidence" else f"{n.func.id}(argument_name=value)"
                raise ExecutionError("invalid_ast",f"tool calls require keyword arguments; use {example} with the documented parameter names")


class _Interpreter:
    def __init__(self, maxops:int, tool_names):
        self.env={}; self.deps={}; self.stale=set(); self.ops=0; self.maxops=maxops; self.out=[]; self.tool_calls=[]; self.last_sources=[]; self.output_len=0;self.output_truncated=False;self.tool_names=set(tool_names)
    def tick(self):
        self.ops+=1
        if self.ops>self.maxops: raise ExecutionError("quota","operation quota exceeded")
    def apply_binop(self,op,a,b):
        if isinstance(op,ast.Pow) and (abs(b)>1000 or abs(a)>1e6):
            raise ExecutionError("quota","power operation too large")
        if isinstance(op,ast.Mult) and (
            isinstance(a,(str,list,tuple)) and isinstance(b,int) and len(a)*max(0,b)>_MAX_VALUE
            or isinstance(b,(str,list,tuple)) and isinstance(a,int) and len(b)*max(0,a)>_MAX_VALUE
        ):
            raise ExecutionError("quota","repeated value too large")
        value=_BIN[type(op)](a,b)
        self.bound(value)
        return value
    def ev(self,n):
        self.tick()
        if isinstance(n,ast.Constant): return n.value
        if isinstance(n,ast.Name):
            if n.id in self.stale: raise ExecutionError("stale_source",f"variable {n.id} depends on stale source")
            if n.id in self.env: return self.env[n.id]
            if n.id in _BUILTINS:return _BUILTINS[n.id]
            if n.id in self.tool_names or n.id=="print":return n.id
            raise ExecutionError("name_error",f"undefined name: {n.id}")
        if isinstance(n,(ast.List,ast.Tuple)): return [self.ev(x) for x in n.elts] if isinstance(n,ast.List) else tuple(self.ev(x) for x in n.elts)
        if isinstance(n,ast.Dict): return {self.ev(k):self.ev(v) for k,v in zip(n.keys,n.values)}
        if isinstance(n,ast.Subscript): return self.ev(n.value)[self.ev(n.slice)]
        if isinstance(n,ast.Slice): return slice(self.ev(n.lower) if n.lower else None,self.ev(n.upper) if n.upper else None,self.ev(n.step) if n.step else None)
        if isinstance(n,ast.UnaryOp): return not self.ev(n.operand) if isinstance(n.op,ast.Not) else (-self.ev(n.operand) if isinstance(n.op,ast.USub) else +self.ev(n.operand))
        if isinstance(n,ast.BinOp):
            a,b=self.ev(n.left),self.ev(n.right)
            return self.apply_binop(n.op,a,b)
        if isinstance(n,ast.BoolOp):
            v=self.ev(n.values[0])
            for x in n.values[1:]:
                if (isinstance(n.op,ast.And) and not v) or (isinstance(n.op,ast.Or) and v): return v
                v=self.ev(x)
            return v
        if isinstance(n,ast.Compare):
            a=self.ev(n.left)
            for op,right in zip(n.ops,n.comparators):
                b=self.ev(right)
                if not _CMP[type(op)](a,b): return False
                a=b
            return True
        if isinstance(n,ast.Call):
            f=self.ev(n.func); args=[self.ev(x) for x in n.args]
            if f=="print":
                rendered=" ".join(map(str,args)); available=max(0,_MAX_OUTPUT-self.output_len)
                self.out.append(rendered[:available]);self.output_len+=min(len(rendered),available)
                if len(rendered)>available:self.output_truncated=True
                return None
            if isinstance(f,str) and f in self.tool_names:
                kw={x.arg:self.ev(x.value) for x in n.keywords}
                try:res=self.rpc(f,kw)
                except Exception as err:
                    self.tool_calls.append({"name":f,"args":kw,"error":str(err)[:1000]});raise
                self.tool_calls.append({"name":f,"args":kw,"result":res})
                if isinstance(res,dict) and res.get("finished") is True:
                    raise _ExecutionFinished()
                if isinstance(res,dict) and res.get("path") and res.get("file_hash"):
                    self.last_sources.append({"path":res["path"],"file_hash":res["file_hash"]})
                if isinstance(res,dict) and res.get("changed") and res.get("path"):
                    for var, deps in self.deps.items():
                        if any(d.get("path")==res["path"] for d in deps): self.stale.add(var)
                return res
            for a in args:
                if isinstance(a,range) and len(a)>_MAX_VALUE: raise ExecutionError("quota","range too large")
            v=f(*args)
            if isinstance(v,range) and len(v)>_MAX_VALUE: raise ExecutionError("quota","range too large")
            if isinstance(v,(enumerate,zip)): v=list(v)
            self.bound(v); return v
        raise ExecutionError("invalid_ast",f"unsupported expression: {type(n).__name__}")
    def bound(self,v):
        if isinstance(v,(str,list,tuple,dict)) and len(v)>_MAX_VALUE: raise ExecutionError("quota","container too large")
    def target(self,t,v):
        if isinstance(t,ast.Name): self.env[t.id]=v
        elif isinstance(t,(ast.Tuple,ast.List)):
            if len(t.elts)!=len(v): raise ExecutionError("value_error","unpack length mismatch")
            for a,b in zip(t.elts,v): self.target(a,b)
        elif isinstance(t,ast.Subscript): self.ev(t.value)[self.ev(t.slice)]=v
    def stmt(self,s):
        self.tick()
        if isinstance(s,ast.Assign):
            self.last_sources=[]
            v=self.ev(s.value)
            refs=[]
            for n in ast.walk(s.value):
                if isinstance(n,ast.Name) and n.id in self.deps: refs.extend(self.deps[n.id])
            srcs=[]
            for d in refs+self.last_sources:
                if d not in srcs:srcs.append(d)
            for t in s.targets:
                self.target(t,v)
                for n in ast.walk(t):
                    if isinstance(n,ast.Name):
                        self.deps[n.id]=srcs
                        self.stale.discard(n.id)
        elif isinstance(s,ast.AugAssign):
            refs=[]
            for n in list(ast.walk(s.target))+list(ast.walk(s.value)):
                if isinstance(n,ast.Name):refs.extend(self.deps.get(n.id,[]))
            a=self.ev(s.target); b=self.ev(s.value); self.target(s.target,self.apply_binop(s.op,a,b))
            for n in ast.walk(s.target):
                if isinstance(n,ast.Name):self.deps[n.id]=_unique_sources(refs)
        elif isinstance(s,ast.Expr): self.ev(s.value)
        elif isinstance(s,ast.If):
            for x in (s.body if self.ev(s.test) else s.orelse): self.stmt(x)
        elif isinstance(s,ast.For):
            it=self.ev(s.iter)
            if not isinstance(it,(range,list,tuple,str,dict)): raise ExecutionError("type_error","for requires a bounded collection")
            if len(it)>_MAX_VALUE: raise ExecutionError("quota","loop too large")
            srcs=[]
            for n in ast.walk(s.iter):
                if isinstance(n,ast.Name):srcs.extend(self.deps.get(n.id,[]))
            for n in ast.walk(s.target):
                if isinstance(n,ast.Name):self.deps[n.id]=_unique_sources(srcs);self.stale.discard(n.id)
            for v in it:self.target(s.target,v); [self.stmt(x) for x in s.body]
            if s.orelse:[self.stmt(x) for x in s.orelse]
    def rpc(self,name,args):
        raise NotImplementedError

def _json_put(q,obj): q.put(json.dumps(obj,ensure_ascii=False,separators=(",",":")))
def _json_get(q): return json.loads(q.get())

def _worker(inq,outq,maxops,tool_names):
    for key in list(os.environ):
        if any(x in key.upper() for x in ("API_KEY","TOKEN","SECRET","PASSWORD","CREDENTIAL")): os.environ.pop(key,None)
    it=_Interpreter(maxops,tool_names)
    def rpc(name,args):
        _json_put(outq,("tool",name,args)); msg=_json_get(inq)
        if msg[0]!="tool_result": raise ExecutionError("rpc_error","invalid tool response")
        if msg[1].get("error"): raise ExecutionError("tool_error",str(msg[1]["error"]))
        return msg[1]
    it.rpc=rpc
    while True:
        msg=_json_get(inq)
        if msg[0]=="close":return
        if msg[0]=="reset":it=_Interpreter(maxops,tool_names);it.rpc=rpc;continue
        _,code,stale=msg; it.ops=0; it.out=[];it.output_len=0;it.output_truncated=False;it.tool_calls=[];it.stale=set(stale)
        try:
            tree=ast.parse(code,mode="exec");_validate(tree,tool_names)
            for s in tree.body:it.stmt(s)
            _json_put(outq,("done",{"stdout":"".join(it.out),"output_truncated":it.output_truncated,"error":None,"tool_calls":it.tool_calls,"namespace":_namespace(it),"sources":it.deps}))
        except _ExecutionFinished:
            _json_put(outq,("done",{"stdout":"".join(it.out),"output_truncated":it.output_truncated,"error":None,"tool_calls":it.tool_calls,"namespace":_namespace(it),"sources":it.deps,"finished":True}))
        except Exception as e:
            code=getattr(e,"code","runtime_error");_json_put(outq,("done",{"stdout":"".join(it.out),"output_truncated":it.output_truncated,"error":{"code":code,"message":str(e)[:2000]},"tool_calls":it.tool_calls,"namespace":_namespace(it),"sources":it.deps}))

def _namespace(it):
    return [{"name":k,"type":type(v).__name__,"size":len(v) if isinstance(v,(str,list,tuple,dict)) else None,"stale":k in it.stale} for k,v in sorted(it.env.items())]

class PythonExecutor:
    def __init__(self,timeout_seconds=30,max_operations=50000,max_tool_calls=16,tool_names=None):
        self.timeout_seconds=timeout_seconds; self.max_operations=max_operations;self.max_tool_calls=max_tool_calls
        self.tool_names=set(tool_names or _DEFAULT_TOOLS)
        self.ctx=mp.get_context("spawn");self._start_worker()
        self.sources={}; self.closed=False
    def _start_worker(self):
        self.iq=self.ctx.Queue();self.oq=self.ctx.Queue();self.p=self.ctx.Process(target=_worker,args=(self.iq,self.oq,self.max_operations,sorted(self.tool_names)),daemon=True);self.p.start()
    def reset(self):
        if self.closed:
            self.closed=False;self._start_worker()
        else:_json_put(self.iq,("reset",))
        self.sources={}
    def close(self):
        if self.closed:return
        _json_put(self.iq,("close",));self.p.join(1)
        if self.p.is_alive():self.p.terminate();self.p.join()
        self.closed=True
    def execute(self,code,invoke,validate_sources=None):
        if self.closed:return {"stdout":"","output_truncated":False,"error":{"code":"closed","message":"executor is closed; call reset() to restart"},"tool_calls":[],"namespace":[]}
        stale=[]
        for var,src in self.sources.items():
            if validate_sources is not None and not validate_sources({x["path"]:x["file_hash"] for x in src}):stale.append(var)
        _json_put(self.iq,("run",code,stale)); deadline=time.monotonic()+self.timeout_seconds; calls=0; completed=[]
        while True:
            remain=deadline-time.monotonic()
            if remain<=0:
                self.p.terminate();self.p.join();self.closed=True
                return {"stdout":"","output_truncated":False,"error":{"code":"timeout","message":"computation timed out"},"tool_calls":completed,"namespace":[]}
            try: msg=json.loads(self.oq.get(timeout=min(remain,.2)))
            except queue.Empty: msg=None
            except Exception: msg=None
            if msg is None:
                try: time.sleep(min(remain,.02))
                except Exception: pass
                if not self.p.is_alive():return {"stdout":"","output_truncated":False,"error":{"code":"worker_crash","message":"worker exited"},"tool_calls":completed,"namespace":[]}
                continue
            if msg[0]=="tool":
                _,name,args=msg;calls+=1
                if calls>self.max_tool_calls: result={"error":"tool call quota exceeded"}
                else:
                    before=time.monotonic()
                    try: result=invoke(name,args)
                    except Exception as e: result={"error":str(e)}
                    duration=time.monotonic()-before;deadline+=duration
                if not isinstance(result,dict): result={"error":"tool result must be a dict"}
                path=result.get("path")
                if path and result.get("changed"):
                    self.sources={k:v for k,v in self.sources.items() if not any(d.get("path")==path for d in v)}
                _json_put(self.iq,("tool_result",result))
                completed.append({"name":name,"args":args,"result":result})
                continue
            if msg[0]=="done":
                r=msg[1]; self.sources={k:v for k,v in r.get("sources",{}).items() if v};return r
