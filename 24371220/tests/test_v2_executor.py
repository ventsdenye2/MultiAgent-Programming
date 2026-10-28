import unittest

from codeagent.executor import PythonExecutor, ParseError, parse_code


class ExecutorTests(unittest.TestCase):
    def test_parse_single_block(self):
        self.assertEqual(parse_code("Answer:\n```python\nx=1\n```"), "x=1")
        with self.assertRaises(ParseError): parse_code("```python\nx=1\n```\n```py\ny=2\n```")
        with self.assertRaises(ParseError): parse_code("no code")

    def run_exec(self, code, **kwargs):
        ex=PythonExecutor(timeout_seconds=kwargs.pop("timeout_seconds",4), **kwargs)
        try:return ex.execute(code,kwargs.get("invoke",lambda n,a:{}),kwargs.get("validate_sources"))
        finally:ex.close()

    def test_tools_and_persistent_variables(self):
        calls=[]
        ex=PythonExecutor(timeout_seconds=4)
        try:
            a=ex.execute("r = read_file(path='a')\nx = r['value'] + 2\nprint(x)",lambda n,a:(calls.append((n,a)) or {"value":3,"path":"a","file_hash":"h"}))
            b=ex.execute("y = x * 3\nprint(y)",lambda n,a:{})
            self.assertEqual(a["stdout"],"5");self.assertEqual(b["stdout"],"15")
            self.assertEqual(len(a["tool_calls"]),1)
        finally:ex.close()

    def test_rejects_unsafe_ast_and_reserved_names(self):
        for code in ("import os", "x = open('secret')", "while True: pass", "read = 1", "x = (1).__class__"):
            r=self.run_exec(code)
            self.assertIsNotNone(r["error"],code)

    def test_quota_and_timeout(self):
        self.assertEqual(self.run_exec("for i in range(20):\n x = i",max_operations=5)["error"]["code"],"quota")
        self.assertEqual(self.run_exec("for i in range(999999999):\n x=i",timeout_seconds=1)["error"]["code"],"quota")

    def test_tool_failure_keeps_prior_work_and_stops(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            r=ex.execute("x=7\nread_file(path='a')\ny=8",lambda n,a:{"error":"denied"})
            self.assertEqual(r["error"]["code"],"tool_error")
            r2=ex.execute("print(x)",lambda n,a:{})
            self.assertEqual(r2["stdout"],"7")
            self.assertNotIn("y",[x["name"] for x in r2["namespace"]])
        finally: ex.close()

    def test_stale_source_rejected(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            ex.execute("r=read_file(path='p')\nx=r['value']",lambda n,a:{"value":4,"path":"p","file_hash":"old"})
            r=ex.execute("print(x)",lambda n,a:{},lambda src:False)
            self.assertEqual(r["error"]["code"],"stale_source")
        finally:ex.close()

    def test_write_invalidates_earlier_source_in_same_block(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            r=ex.execute("r=read_file(path='p')\nx=r['value']\nwrite_file(path='p', content='new')\nprint(x)",
                lambda n,a:({"value":9,"path":"p","file_hash":"old"} if n=="read_file" else {"path":"p","changed":True}))
            self.assertEqual(r["error"]["code"],"stale_source")
        finally:ex.close()

    def test_new_tool_names_and_keyword_arguments(self):
        ex=PythonExecutor(timeout_seconds=4,tool_names={"search_code","save_note"})
        calls=[]
        try:
            r=ex.execute("hits=search_code(query='needle', limit=3)\nsave_note(title='x', body='y')",lambda n,a:(calls.append((n,a)) or {"ok":True}))
            self.assertIsNone(r["error"])
            self.assertEqual(calls,[('search_code',{'query':'needle','limit':3}),('save_note',{'title':'x','body':'y'})])
        finally:ex.close()

    def test_reset_rebinds_rpc_and_close_is_reported(self):
        ex=PythonExecutor(timeout_seconds=4)
        ex.reset()
        try:
            r=ex.execute("read_file(path='after-reset')",lambda n,a:{"ok":True})
            self.assertIsNone(r["error"])
        finally:ex.close()
        self.assertEqual(ex.execute("x=1",lambda n,a:{})["error"]["code"],"closed")

    def test_alias_and_loop_variable_keep_source(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            first=ex.execute("rows=read_file(path='p')\nalias=rows['items']\nfor item in alias:\n last=item",lambda n,a:{"items":[1],"path":"p","file_hash":"h"})
            self.assertIsNone(first["error"],first)
            r=ex.execute("print(last)",lambda n,a:{},lambda sources:False)
            self.assertEqual(r["error"]["code"],"stale_source")
        finally:ex.close()

    def test_multiple_sources_are_unioned(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            ex.execute("a=read_file(path='a')\nb=read_file(path='b')\nc=a['n'] + b['n']",lambda n,a:{"n":1,"path":a["path"],"file_hash":"h"})
            r=ex.execute("print(c)",lambda n,a:{},lambda src: "b" not in src)
            self.assertEqual(r["error"]["code"],"stale_source")
        finally:ex.close()

    def test_print_has_execution_time_limit(self):
        r=self.run_exec("print('x' * 30000)")
        self.assertTrue(r["output_truncated"])
        self.assertEqual(len(r["stdout"]),20000)

    def test_successful_finish_stops_remaining_statements(self):
        calls=[]
        ex=PythonExecutor(timeout_seconds=4)
        try:
            r=ex.execute(
                "x=1\nprint('before')\nfinish(summary='done')\ny=2\nprint('after')\nread_file(path='never')",
                lambda n,a:(calls.append((n,a)) or {"finished":True}))
            self.assertIsNone(r["error"])
            self.assertEqual(r["stdout"],"before")
            self.assertEqual([item["name"] for item in r["namespace"]],["x"])
            self.assertEqual(len(r["tool_calls"]),1)
            self.assertEqual([name for name,_ in calls],["finish"])
        finally:ex.close()


if __name__ == "__main__": unittest.main()
