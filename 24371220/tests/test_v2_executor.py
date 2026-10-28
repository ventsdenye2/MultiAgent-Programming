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

    def test_print_budget_resets_between_rounds_but_namespace_persists(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            first=ex.execute("x=41\nprint('a' * 20001)",lambda n,a:{})
            second=ex.execute("print(x + 1)",lambda n,a:{})
            self.assertTrue(first["output_truncated"])
            self.assertEqual(len(first["stdout"]),20000)
            self.assertFalse(second["output_truncated"])
            self.assertEqual(second["stdout"],"42")
            self.assertEqual([item["name"] for item in second["namespace"]],["x"])
        finally:ex.close()

    def test_print_budget_still_accumulates_within_one_round(self):
        r=self.run_exec("print('a' * 15000)\nprint('b' * 7000)")
        self.assertTrue(r["output_truncated"])
        self.assertEqual(len(r["stdout"]),20000)
        self.assertTrue(r["stdout"].startswith("a" * 15000))
        self.assertTrue(r["stdout"].endswith("b" * 5000))

    def test_augassign_numeric_and_source_dependencies(self):
        ex=PythonExecutor(timeout_seconds=4)
        try:
            first=ex.execute("r=read_file(path='p')\nx=1\nx += r['value']\nprint(x)",
                lambda n,a:{"value":4,"path":"p","file_hash":"h"})
            self.assertIsNone(first["error"],first)
            self.assertEqual(first["stdout"],"5")
            self.assertIn({"path":"p","file_hash":"h"},first["sources"]["x"])
            second=ex.execute("print(x)",lambda n,a:{},lambda sources:False)
            self.assertEqual(second["error"]["code"],"stale_source")
        finally:ex.close()

    def test_augassign_obeys_binop_resource_quotas(self):
        repeated=self.run_exec("s='x'\ns *= 1000001")
        power=self.run_exec("x=2\nx **= 1001")
        self.assertEqual(repeated["error"]["code"],"quota")
        self.assertEqual(power["error"]["code"],"quota")

    def test_real_run_syntax_errors_offer_executable_recovery(self):
        cases = [
            ("r=read_file(path='a')\nprint(r.get('content'))",
             "result['key']", "r=read_file(path='a')\nprint(r['content'])"),
            ("r=get_evidence('ev-1')", "get_evidence(evidence_id=",
             "r=get_evidence(evidence_id='ev-1')\nprint(r['content'])"),
        ]
        for bad, hint, good in cases:
            with self.subTest(code=bad):
                calls=[]
                ex=PythonExecutor(timeout_seconds=4)
                invoke=lambda name,args:(calls.append(name) or {'content':'recovered'})
                try:
                    failed=ex.execute(bad,invoke)
                    self.assertEqual(failed['error']['code'],'invalid_ast')
                    self.assertIn(hint,failed['error']['message'])
                    self.assertEqual(calls,[]) # validation cannot partially execute tools
                    recovered=ex.execute(good,invoke)
                    self.assertIsNone(recovered['error'])
                    self.assertEqual(recovered['stdout'],'recovered')
                    self.assertEqual(len(calls),1)
                finally:ex.close()

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
