"""Contributor-scoped editing, combined review and immutable section approval."""
from collections import defaultdict
from copy import deepcopy
import json
from app.db.repository import _now_iso,_uid

def atomic_report(method):
    from functools import wraps
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        week_id=kwargs['reporting_week_id']
        with self.repo.db.transaction():
            self.repo.db.lock_reporting_week(week_id)
            result=method(self,*args,**kwargs)
            snapshot=self.repo.get_week_bundle(week_id)
            if kwargs.get('extra_narratives'):snapshot['narratives']=kwargs['extra_narratives']
            self.repo.save_generation_snapshot(result['generation']['id'],snapshot)
            result['_snapshot_saved']=True
            return result
    return wrapped

def participants(repo,project,submissions=()):
    people={}
    ids=[project.get('owner_user_id')]+[m['user_id'] for m in repo.list_project_members(project['id']) if m['member_role'] in ('manager','contributor')]
    for uid in ids:
        if not uid:continue
        user=repo.get_user(uid)
        if user and user['is_active']:people[uid]=user
    for sub in submissions:
        user=repo.get_user(sub['submitted_by'])
        if user:people.setdefault(user['id'],user)
    return list(people.values())

def section_state(repo,week_id,project):
    subs=[s for s in repo.list_submissions_for_week(week_id) if s['project_id']==project['id']]
    by_user={s['submitted_by']:s for s in subs}
    contributors=[{'user_id':u['id'],'full_name_ar':u['full_name_ar'],'status':by_user.get(u['id'],{}).get('status','not_started'),'last_updated':by_user.get(u['id'],{}).get('updated_at')} for u in participants(repo,project,subs)]
    approval=repo.db.fetch_one('SELECT * FROM project_approvals WHERE reporting_week_id=? AND project_id=?',(week_id,project['id']))
    statuses=[c['status'] for c in contributors]
    if approval:status='approved'
    elif not subs:status='not_started'
    elif 'changes_requested' in statuses:status='changes_requested'
    elif statuses and all(s=='approved' for s in statuses):status='approved'
    elif statuses and all(s in ('submitted','approved') for s in statuses):status='submitted'
    else:status='draft'
    return {'status':status,'contributors':contributors,'submissions':subs,'approval':approval,'missing_contributors':[c for c in contributors if c['status']=='not_started']}

def _combine_bundle(repo,bundle):
    """Keep every narrative; ambiguous shared numbers need a coordinator choice."""
    users={u['id']:u['full_name_ar'] for u in repo.list_users()}
    project_codes={p['id']:p['project_code'] for p in bundle['projects']}
    for row in bundle.get('news',[])+bundle.get('events',[]):
        row.setdefault('project_code',project_codes.get(row.get('project_id'),''))
    for key in ('achievements','upcoming_tasks','kpis','news','events'):
        for row in bundle.get(key,[]):
            uid=row['responsible_user_id']
            if uid not in users:users[uid]=(repo.get_user(uid) or {}).get('full_name_ar',uid)
    for collection,kind,index,text in [('achievements','achievement','slot_index','content_ar'),('upcoming_tasks','task','sequence_no','title_ar'),('news','news','slot_index','body_ar')]:
        groups=defaultdict(list)
        for row in bundle[collection]:groups[(row.get('project_code'),row.get('task_kind','achievement'))].append(row)
        for rows in groups.values():
            rows.sort(key=lambda r:(r['responsible_user_id'],r[index],r['id']))
            multiple=len({r['responsible_user_id'] for r in rows})>1
            for number,row in enumerate(rows,1):
                row['contributor_slot']=row[index];row[index]=number;row['original_text']=row[text]
                row['contributor_name']=users.get(row['responsible_user_id'],'')
                if multiple:row[text]=row['contributor_name']+' — '+row[text]
    event_groups=defaultdict(list)
    for event in bundle['events']:event_groups[event['slot_key']].append(event)
    merged_events=[]
    for rows in event_groups.values():
        item=deepcopy(rows[0])
        if len(rows)>1:
            item['title_ar']='\n'.join(users.get(r['responsible_user_id'],'')+' — '+r['title_ar'] for r in rows)
            item['event_date_label']=' / '.join(dict.fromkeys(r.get('event_date_label') or '' for r in rows))
        merged_events.append(item)
    bundle['events']=merged_events
    approvals={a['project_id']:a for a in repo.db.fetch_all('SELECT * FROM project_approvals WHERE reporting_week_id=?',(bundle['reporting_week']['id'],))}
    bundle['individual_kpis']=deepcopy(bundle['kpis'])
    bundle['individual_project_statuses']=deepcopy(bundle['project_statuses'])
    by_kpi=defaultdict(list)
    for row in bundle['kpis']:by_kpi[row['kpi_code']].append(row)
    selected=[];conflicts=[]
    for code,rows in by_kpi.items():
        meaningful=[r for r in rows if r['numeric_value'] is not None]
        values={(r['numeric_value'],r.get('denominator_value')) for r in meaningful}
        approval=approvals.get(rows[0]['project_id'],{})
        source=json.loads(approval.get('kpi_sources_json') or '{}').get(code) or approval.get('kpi_source_user_id')
        chosen=next((r for r in meaningful if r['responsible_user_id']==source),None)
        if len(values)>1 and not chosen:
            conflicts.append({'project_id':rows[0]['project_id'],'kpi_code':code,'label_ar':rows[0]['label_ar'],'contributors':[{'user_id':r['responsible_user_id'],'name':users.get(r['responsible_user_id'],''),'value':r['numeric_value'],'denominator':r.get('denominator_value')} for r in meaningful]})
            chosen={**rows[0],'numeric_value':None,'denominator_value':None}
        selected.append(chosen or (meaningful or rows)[0])
    bundle['kpis']=selected;bundle['kpi_conflicts']=conflicts
    # Status badges reflect the most urgent contributor assessment, never last writer wins.
    severity={'critically_delayed':0,'delayed':1,'on_hold':2,'not_started':3,'on_track':4,'completed':5}
    by_status=defaultdict(list)
    for r in bundle['project_statuses']:by_status[r['project_id']].append(r)
    bundle['project_statuses']=[min(rows,key=lambda r:severity[r['status_code']]) for rows in by_status.values()]
    return bundle

def attach_collaboration(repo_cls,lifecycle_cls):
    if getattr(repo_cls,'_collaboration_attached',False):return
    repo_cls._collaboration_attached=True
    old_detail=repo_cls.get_project_week_detail
    def detail(self,week_id,project_id,contributor_id=None):
        result=old_detail(self,week_id,project_id)
        if contributor_id is None:return result
        result['submission']=self.get_submission(week_id,project_id,contributor_id)
        for key in ('kpis','achievements','upcoming_tasks','challenges','events','news'):
            result[key]=[r for r in result[key] if r['responsible_user_id']==contributor_id]
        result['project_status']=self.db.fetch_one('SELECT * FROM project_statuses WHERE reporting_week_id=? AND project_id=? AND responsible_user_id=?',(week_id,project_id,contributor_id))
        return result
    repo_cls.get_project_week_detail=detail

    old_bundle=repo_cls.get_week_bundle
    def bundle(self,week_id):return _combine_bundle(self,old_bundle(self,week_id))
    repo_cls.get_week_bundle=bundle

    old_submit=lifecycle_cls.submit_weekly_update
    def submit(self,reporting_week_id,payload,actor_user_id,uploads_dir=None):
        with self.repo.db.transaction():
            self.repo.db.lock_reporting_week(reporting_week_id)
            if self.repo.db.fetch_one('SELECT id FROM project_approvals WHERE reporting_week_id=? AND project_id=?',(reporting_week_id,payload.project_id)):
                raise PermissionError('تم اعتماد تحديثات القسم. يجب أن يعيد المنسق فتحه للتعديل أولًا.')
            return old_submit(self,reporting_week_id,payload,actor_user_id,uploads_dir)
    lifecycle_cls.submit_weekly_update=submit

    old_complete=lifecycle_cls.compute_completeness
    def complete(self,week_id):
        result=old_complete(self,week_id)
        done=[];missing=[]
        for p in self.repo.list_projects():
            if not p.get('is_enabled',1):continue
            state=section_state(self.repo,week_id,p)
            row={'project_id':p['id'],'project_code':p['project_code'],'status':state['status'],'contributors':state['contributors']}
            (done if state['status'] in ('submitted','approved') else missing).append(row)
        result.update(submitted_projects=done,missing_projects=missing,completion_pct=round(100*len(done)/(len(done)+len(missing)),1) if done or missing else 100)
        result['is_complete']=not missing and not result['missing_kpis'] and not result['null_kpis']
        return result
    lifecycle_cls.compute_completeness=complete

    def review(self,*,reporting_week_id,project_id,status,reviewer_notes_ar,reviewer_user_id,kpi_source_user_id=None,expected_versions=None,kpi_sources=None):
        with self.db.transaction():
            week=self.db.lock_reporting_week(reporting_week_id)
            if not week or week['status'] in ('locked','archived'):raise ValueError('الأسبوع مقفل أو مؤرشف.')
            project=self.get_project(project_id)
            if not project:raise KeyError('القسم غير موجود.')
            state=section_state(self,reporting_week_id,project)
            if not state['submissions']:raise KeyError('لا توجد تحديثات لهذا القسم.')
            if expected_versions is not None and expected_versions != {s['id']:s['version'] for s in state['submissions']}:
                raise ValueError('تغيرت تحديثات القسم أثناء المراجعة. افتح المراجعة مجددًا قبل الاعتماد.')
            if status=='approved':
                if state['missing_contributors']:raise ValueError('لم يحفظ تحديثه بعد: '+', '.join(c['full_name_ar'] for c in state['missing_contributors']))
                conflicts=[c for c in self.get_week_bundle(reporting_week_id).get('kpi_conflicts',[]) if c['project_id']==project_id]
                kpi_sources=kpi_sources or {}
                if conflicts and any(not any(x['user_id']==(kpi_sources.get(c['kpi_code']) or kpi_source_user_id) for x in c['contributors']) for c in conflicts):
                    raise ValueError('توجد أرقام مؤشرات مختلفة. اختر مصدر الأرقام في نافذة الاعتماد.')
                if kpi_source_user_id and kpi_source_user_id not in {s['submitted_by'] for s in state['submissions']}:raise ValueError('مصدر الأرقام ليس من أصحاب التحديثات.')
                self.db.execute('INSERT INTO project_approvals(id,reporting_week_id,project_id,approved_by,approved_at,kpi_source_user_id) VALUES (?,?,?,?,?,?) ON CONFLICT(reporting_week_id,project_id) DO UPDATE SET approved_by=excluded.approved_by,approved_at=excluded.approved_at,kpi_source_user_id=excluded.kpi_source_user_id',(_uid('approval'),reporting_week_id,project_id,reviewer_user_id,_now_iso(),kpi_source_user_id))
                self.db.execute('UPDATE project_approvals SET kpi_sources_json=? WHERE reporting_week_id=? AND project_id=?',(json.dumps(kpi_sources),reporting_week_id,project_id))
            else:self.db.execute('DELETE FROM project_approvals WHERE reporting_week_id=? AND project_id=?',(reporting_week_id,project_id))
            for s in state['submissions']:
                self.db.execute('UPDATE weekly_submissions SET status=?, reviewed_by=?, reviewer_notes_ar=?, updated_at=? WHERE id=?',(status,reviewer_user_id,reviewer_notes_ar,_now_iso(),s['id']))
                self.record_audit(entity_type='weekly_submission',entity_id=s['id'],action='review:'+status,actor_user_id=reviewer_user_id,reporting_week_id=reporting_week_id,old_value={'status':s['status']},new_value={'status':status,'reviewer_notes_ar':reviewer_notes_ar})
            for table in ('achievements','upcoming_tasks','challenges','kpi_values','events','news','project_statuses'):
                self.db.execute(f'UPDATE {table} SET submission_status=? WHERE reporting_week_id=? AND project_id=?',(status,reporting_week_id,project_id))
            return {**self.get_submission(reporting_week_id,project_id),'reviewed_count':len(state['submissions'])}
    repo_cls.review_submission=review

def require_approved_contributions(repo,week_id):
    conflicts=repo.get_week_bundle(week_id).get('kpi_conflicts',[])
    if conflicts:raise ValueError('أرقام مؤشرات غير محسومة. راجع اعتماد الأقسام قبل توليد التقرير.')
