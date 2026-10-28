"""Evidence provenance and note lifecycle for Code Agent v2."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
from typing import Any

READ_TOOLS = {"read_file", "read_range", "read_symbol", "read_pdf"}
TOPICS = ("overview", "reasoning", "tool_use", "multi_agent", "outlook")

class EvidenceStore:
    def __init__(self, log, root):
        self.log, self.root = log, Path(root).resolve()
        self.records: dict[str, dict[str, Any]] = {}
        self._serial = 0

    def _log(self, event, **data):
        if callable(self.log): self.log(event, **data)

    def _new_id(self, prefix):
        self._serial += 1
        return f"{prefix}-{self._serial:06d}"

    def observe(self, tool, args, result, step_id):
        if tool not in READ_TOOLS or not isinstance(result, dict) or result.get("error") or result.get("rc", 0) != 0: return []
        if tool == "read_pdf":
            payload = result.get("content")
            pages = result.get("pages") or (payload.get("pages") if isinstance(payload, dict) else payload if isinstance(payload, list) else None)
            if pages is None: return []
            pdf_path=result.get("pdf",result.get("pdf_path",args.get("pdf",args.get("path",""))))
            pdf_path=str(pdf_path)
            p=Path(pdf_path)
            if p.is_absolute():
                try: pdf_path=p.resolve().relative_to(self.root).as_posix()
                except ValueError: raise ValueError('PDF evidence must stay inside the workspace')
            else: pdf_path=Path(pdf_path).as_posix()
            if not (self.root/pdf_path).resolve().is_relative_to(self.root):
                raise ValueError('PDF evidence must stay inside the workspace')
            digest=result.get("file_hash")
            if digest is None and pdf_path:
                try: digest=hashlib.sha256((self.root/pdf_path).read_bytes()).hexdigest()
                except OSError: digest=None
            out=[]
            for item in pages:
                page = item.get("page") if isinstance(item,dict) else None
                content = item.get("text", item.get("content", "")) if isinstance(item,dict) else str(item)
                if not isinstance(content,str): content=json.dumps(content,ensure_ascii=False)
                rid=self._new_id("ev")
                self.records[rid] = {"id":rid,"content":content,"path":pdf_path,"file_hash":digest,"kind":"pdf","start_line":None,"end_line":None,"page":page,"status":"valid","seen_requests":[],"successful_requests":[],"step_id":step_id,"sources":[]}
                out.append(rid)
            return out
        content=result.get("content"); path=result.get("path", args.get("path"))
        if not isinstance(content,str) or not isinstance(path,str): return []
        rid=self._new_id("ev"); p=Path(path)
        if not p.is_absolute(): p=(self.root/p).resolve()
        try: rel=p.relative_to(self.root).as_posix()
        except ValueError: raise ValueError('Source evidence must stay inside the workspace')
        kind={"read_file":"file","read_range":"range","read_symbol":"symbol"}[tool]
        self.records[rid]={"id":rid,"content":content,"path":rel,"file_hash":result.get("file_hash"),"kind":kind,"start_line":result.get("start_line"),"end_line":result.get("end_line"),"page":None,"status":"valid","seen_requests":[],"successful_requests":[],"step_id":step_id,"sources":[]}
        return [rid]

    def mark_sent(self, request_id, evidence_ids):
        for rid in evidence_ids:
            if rid in self.records:
                rec=self.records[rid]
                if request_id not in rec.setdefault("seen_requests",[]): rec["seen_requests"].append(request_id)
        self._log('evidence_sent',request_id=request_id,evidence_ids=list(evidence_ids))

    def mark_response(self, request_id, success=True):
        for rec in self.records.values():
            if request_id in rec.get("seen_requests",[]) and success and rec.get("status")!="invalid":
                if request_id not in rec.setdefault("successful_requests",[]): rec["successful_requests"].append(request_id)

    def _invalidate_record(self, rec):
        if rec["status"]=="invalid": return
        rec["status"]="invalid"
        self._log('evidence_invalidated',evidence_id=rec['id'],path=rec.get('path'))
        for child in self.records.values():
            if rec["id"] in child.get("sources",[]): self._invalidate_record(child)

    def invalidate(self, path, new_hash):
        for rec in self.records.values():
            if rec.get("path")==path and rec.get("file_hash") != new_hash: self._invalidate_record(rec)

    def refresh(self):
        hashes={}
        for rec in list(self.records.values()):
            path=rec.get("path"); old=rec.get("file_hash")
            if not path or old is None: continue
            if path in hashes: digest=hashes[path]
            else:
                try: digest=hashlib.sha256((self.root/path).read_bytes()).hexdigest()
                except OSError: digest="missing"
            hashes[path]=digest
            if digest != old: self.invalidate(path,digest)
        return hashes

    @staticmethod
    def _response_strings(text):
        vals=[text]
        for parser in (json.loads, ast.literal_eval):
            try:
                obj=parser(text)
                if isinstance(obj,str): vals.append(obj)
                elif isinstance(obj,dict): vals.extend(v for v in obj.values() if isinstance(v,str))
            except Exception: pass
        # Extract string constants from fenced/plain Python snippets without executing them.
        for block in __import__("re").findall(r"```(?:python|py)?\s*([\s\S]*?)```", text, __import__("re").I):
            try:
                tree=ast.parse(block)
                vals.extend(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str))
            except (SyntaxError,ValueError): pass
        return vals

    def _closure_paths_pages(self, ids):
        seen=set(); paths=set(); pages=[]
        def visit(rid):
            if rid in seen or rid not in self.records:return
            seen.add(rid); r=self.records[rid]
            if r.get("path"): paths.add(r["path"])
            if r.get("kind")=="pdf" and r.get("page") is not None: pages.append(r["page"])
            for s in r.get("sources",[]):visit(s)
        for rid in ids:visit(rid)
        return sorted(paths),sorted(set(pages))

    def save_note(self, content, sources, topic, response_id, response_text, request_id):
        if not isinstance(content,str) or not content.strip():raise ValueError("note content must be nonempty text")
        variants=self._response_strings(response_text)
        if not any(content in s for s in variants): raise ValueError("note content must occur in the actual response text (including decoded escapes)")
        ids=list(dict.fromkeys(sources))
        if not ids or any(i not in self.records for i in ids):raise ValueError("note sources must be existing evidence IDs")
        for i in ids:
            r=self.records[i]
            if request_id not in r.get("successful_requests",[]):raise ValueError("note source was not successfully exposed to this request")
            if r.get("status")!="valid":raise ValueError("note source is invalid")
        def live(i,seen=None):
            seen=seen or set()
            if i in seen:return True
            seen.add(i);r=self.records[i]
            return r.get("status")!="invalid" and all(live(s,seen) for s in r.get("sources",[]))
        if not all(live(i) for i in ids):raise ValueError("note source closure contains invalid evidence")
        paths,pages=self._closure_paths_pages(ids); is_topic=topic in TOPICS
        if is_topic and not 20<=len(content)<=1500:raise ValueError("topic note content must be 20..1500 characters")
        if not is_topic and not 20<=len(content)<=3000:raise ValueError("context note content must be 20..3000 characters")
        nid=self._new_id("note"); versions=[r["version"] for r in self.records.values() if is_topic and r.get("kind")=="topic_note" and r.get("topic")==topic]
        rec={"id":nid,"content":content,"path":None,"file_hash":None,"kind":"topic_note" if is_topic else "context_note","start_line":None,"end_line":None,"page":None,"status":"valid","seen_requests":[],"successful_requests":[],"sources":ids,"source_paths":paths,"pages":pages,"topic":topic,"response_id":response_id,"request_id":request_id,"version":max(versions,default=0)+1}
        self.records[nid]=rec
        if is_topic:self._log("section_note",section=topic,pages=pages,content=content,id=nid,sources=ids)
        else:self._log("context_note",sources=paths,content=content,id=nid,evidence_ids=ids)
        return rec

    def latest_notes(self):
        latest={}
        for r in self.records.values():
            if r.get("kind")=="topic_note" and r.get("status")=="valid" and (r["topic"] not in latest or r["version"]>latest[r["topic"]]["version"]):latest[r["topic"]]=r
        return latest

    def summary(self):
        catalog=[{k:r.get(k) for k in ("id","path","file_hash","kind","start_line","end_line","page","status","topic","version","sources","seen_requests","successful_requests")} for r in self.records.values()]
        return {"counts":{"records":len(catalog),"valid":sum(r["status"]=="valid" for r in catalog),"invalid":sum(r["status"]=="invalid" for r in catalog)},"catalog":catalog,"latest_note_ids":{k:v["id"] for k,v in self.latest_notes().items()}}
