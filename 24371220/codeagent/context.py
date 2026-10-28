"""Whole-request budget context assembly with full action/result pairs."""
from __future__ import annotations
import json

class ContextBuilder:
    def __init__(self, mode='evidence', soft_limit=30000, hard_limit=32000):
        if mode not in ('baseline','diagnostic','evidence') or not 0 < soft_limit <= hard_limit:
            raise ValueError('Invalid context mode or limits')
        self.mode,self.soft_limit,self.hard_limit=mode,soft_limit,hard_limit

    @staticmethod
    def _chars(body):return len(json.dumps(body,ensure_ascii=False,separators=(',',':')))

    def build(self,prefix,history,evidence,state,prepare):
        messages=list(prefix);body=prepare(messages);n=self._chars(body)
        if n>self.hard_limit:raise ValueError(f"固定上下文超过硬限制 ({n} > {self.hard_limit})")
        selected=[];discarded=[];evidence_ids=[];records=evidence.records
        def add(batch,label,required=False,ids=(),allow_soft_overflow=False):
            nonlocal body
            test=prepare(messages+batch);size=self._chars(test)
            if size>self.hard_limit:
                if required:raise ValueError(f"必要上下文 {label} 超过硬限制 ({size} > {self.hard_limit})")
                discarded.append(label);return False
            if size>self.soft_limit and not required and not allow_soft_overflow:
                discarded.append(label);return False
            messages.extend(batch);body=test;selected.append(label);evidence_ids.extend(ids);return True
        required_ids=list(dict.fromkeys(state.get('required_evidence_ids',[])))
        for rid in required_ids:
            if rid not in records:raise ValueError(f"required evidence ID does not exist: {rid}")
            if records[rid].get('status')!='valid':raise ValueError(f"required evidence is invalid: {rid}")
        latest=evidence.latest_notes()
        if state.get('final_notes'):
            missing=[t for t in ('overview','reasoning','tool_use','multi_agent','outlook') if t not in latest]
            if missing:raise ValueError("final_notes requires all five latest topic notes: "+', '.join(missing))
        chosen=[]
        for rid in required_ids:chosen.append((records[rid],True,'required'))
        if state.get('final_notes'):chosen.extend((latest[t],True,'latest_note') for t in ('overview','reasoning','tool_use','multi_agent','outlook') if latest[t]['id'] not in required_ids)
        # All unsent source units are available in every mode. Keep whole PDF pages and symbols.
        pending=[r for r in records.values() if r.get('status')=='valid' and not r.get('successful_requests') and r.get('kind') not in ('topic_note','context_note')]
        focus=state.get('focus_paths',[]);phase=state.get('phase','')
        def rank(r):
            path=r.get('path') or ''
            return (int(r.get('kind')=='pdf')*10+int(any(path==p or path.endswith('/'+p) for p in focus))*6+int(r.get('kind') in ('symbol','range'))*3+int(phase in ('repair','verify') and r.get('kind') in ('symbol','range'))*2,r['id'])
        pending.sort(key=rank,reverse=True)
        added={r['id'] for r,_,_ in chosen}
        chosen.extend((r,True,'unseen') for r in pending if r['id'] not in added)
        added.update(r['id'] for r,_,_ in chosen)
        # Evidence mode reuses current notes and previously exposed source units.
        # A record remains eligible until its file version or source closure expires.
        if self.mode=='evidence':
            reusable=[r for r in records.values() if r.get('status')=='valid' and r['id'] not in added and (r.get('kind')!='topic_note' or latest.get(r.get('topic'),{}).get('id')==r['id'])]
            reusable.sort(key=lambda r:(int(r.get('kind') in ('topic_note','context_note')),rank(r)),reverse=True)
            chosen.extend((r,False,'reuse') for r in reusable)
        unseen_added=0
        for r,req,reason in chosen:
            if r.get('status')!='valid':raise ValueError(f"required evidence is invalid: {r['id']}")
            payload=json.dumps({'evidence_id':r['id'],'path':r.get('path'),'kind':r.get('kind'),'file_hash':r.get('file_hash'),'start_line':r.get('start_line'),'end_line':r.get('end_line'),'page':r.get('page'),'content':r.get('content')},ensure_ascii=False)
            allow=reason=='unseen' and r.get('kind')!='file' and unseen_added==0
            ok=add([{'role':'user','content':payload}],f"{reason}:{r['id']}",req and reason!='unseen', (r['id'],),allow)
            if reason=='unseen' and ok:unseen_added+=1
            if reason=='unseen' and not ok and r.get('kind')=='pdf' and unseen_added==0:
                standalone=prepare(list(prefix)+[{'role':'user','content':payload}])
                if self._chars(standalone)>self.hard_limit:raise ValueError(f"单个 PDF 页面超过硬限制 ({self._chars(standalone)} > {self.hard_limit}): {r['id']}")
        # Full files are optional: when too large, expose a compact catalog to request narrower reads.
        for r in records.values():
            if r.get('kind')!='file' or r.get('status')!='valid' or r.get('seen_requests'):continue
            catalog=json.dumps({'evidence_catalog':{'id':r['id'],'path':r.get('path'),'chars':len(r.get('content','')),'hash':r.get('file_hash')}},ensure_ascii=False)
            add([{'role':'user','content':catalog}],f"catalog:{r['id']}")
        # Optional history selection differs by mode; emit chosen pairs in original chronological order.
        evidence_messages=list(messages[len(prefix):])
        original_pairs=[p for p in history if isinstance(p,dict) and 'assistant' in p and 'observation' in p]
        pairs=list(original_pairs)
        focus_paths=state.get('focus_paths',[])
        if self.mode=='diagnostic':
            pairs.sort(key=lambda p:(int(any(x in json.dumps(p.get('observation'),ensure_ascii=False) for x in focus_paths))*3+int(any(t in json.dumps(p.get('observation'),ensure_ascii=False).lower() for t in ('error','failed','traceback')))*2,str(p.get('step_id',''))),reverse=True)
        else:pairs=list(reversed(pairs))
        accepted=[]
        for p in pairs:
            pair=[{'role':'assistant','content':p['assistant']},{'role':'user','content':p['observation']}]
            if add(pair,f"history:{p.get('step_id')}"):accepted.append(p)
        # Reorder only history messages chronologically, preserving evidence payloads.
        accepted_ids={str(p.get('step_id','')) for p in accepted}
        accepted=[p for p in original_pairs if str(p.get('step_id','')) in accepted_ids]
        hist_messages=[]
        for p in accepted:hist_messages.extend([{'role':'assistant','content':p['assistant']},{'role':'user','content':p['observation']}])
        messages=list(prefix)+hist_messages+evidence_messages;body=prepare(messages)
        if callable(evidence.log):evidence.log('context_selection',mode=self.mode,phase=phase,focus_paths=focus_paths,selected=selected,discarded=discarded,chars=self._chars(body),manifest=[{'id':rid,'path':records[rid].get('path'),'kind':records[rid].get('kind'),'status':records[rid].get('status')} for rid in evidence_ids])
        return {'messages':messages,'evidence_ids':evidence_ids,'chars':self._chars(body),'selected':selected,'discarded':discarded}
