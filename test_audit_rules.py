import ast
import base64
import gzip
import hashlib
import io
import json
import math
import re
import subprocess
import time
import unittest
import unicodedata
from pathlib import Path
from types import SimpleNamespace
import pandas as pd


def generated_source():
    path=Path(__file__).parent
    tree=ast.parse((path/'app.py').read_text(encoding='utf-8'))
    url=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BASE_APP_URL' for t in n.targets))
    base=subprocess.check_output(['git','show',url.split('/')[-2]+':app.py'],cwd=path).decode('utf-8')
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_replace_once','_optimized_source'}]
    env={'_load_base_app':lambda:base}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'bootstrap','exec'),env)
    return env['_optimized_source']()


def app_functions(source=None):
    tree=ast.parse(source or generated_source())
    nodes=[]
    for n in tree.body:
        if isinstance(n,ast.FunctionDef):
            n.decorator_list=[];nodes.append(n)
        elif isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'CLIENT_LOOKUP_B64','SALES_LOOKUP_B64'} for t in n.targets):nodes.append(n)
    env=dict(pd=pd,base64=base64,gzip=gzip,hashlib=hashlib,io=io,json=json,math=math,re=re,unicodedata=unicodedata,Path=Path,DIST='DISTRIBUIDORA DEL VALLE S.A.')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'app_functions','exec'),env)
    return env


class AuditRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.env=app_functions()

    def row(self,**kwargs):
        row={'account_id':'07054900005442','DISTRIBUIDOR':self.env['DIST'],'Comentario_Revision':'Revisar volumen BRAHMA','task_id':'t1','FECHA_TAREA':'2026-09-30','¿Cuantos packs x 24 de BRAHMA 473cc vende por semana?':1}
        row.update(kwargs);return row

    def test_join_and_export_agree(self):
        d=self.env['build'](pd.DataFrame([self.row()]))
        r=d.iloc[0]
        self.assertEqual([r.jun,r.jul,r.aug],[3,1,0])
        self.assertAlmostEqual(r.weekly,28/92)
        state=self.env['fresh'](d);z=self.env['enriched'](d,state)
        exported=self.env['export'](z)
        self.assertAlmostEqual(exported.iloc[0]['Venta prom. mensual'],4/3)
        self.assertEqual(exported.iloc[0]['Unidad'],'packs x24')
        workbook=pd.read_excel(io.BytesIO(self.env['excel'](z,z.iloc[:0])),sheet_name='Correcciones')
        self.assertAlmostEqual(workbook.iloc[0]['Venta prom. semanal'],28/92)

    def test_missing_remains_unknown_but_is_automatic(self):
        r=self.env['build'](pd.DataFrame([self.row(account_id='07054999999999')])).iloc[0]
        self.assertTrue(pd.isna(r.weekly));self.assertTrue(self.env['auto'](r))

    def test_unknown_pack_is_automatic(self):
        row=self.row();row['¿Cuantos cajones de BRAHMA 1 litro OW vende por semana?']=0
        d=self.env['build'](pd.DataFrame([row]))
        r=d[d['product'].eq('BRAHMA / 1 litro OW')].iloc[0]
        self.assertTrue(pd.isna(r.weekly));self.assertTrue(self.env['auto'](r))

    def test_latest_clean_census_replaces_old_flag(self):
        old=self.row(FECHA_TAREA='2026-09-29')
        latest=self.row(task_id='t2',Comentario_Revision='')
        self.assertTrue(self.env['build'](pd.DataFrame([old,latest])).empty)

    def test_distributor_and_finite_controls(self):
        with self.assertRaises(ValueError):self.env['build'](pd.DataFrame([self.row()]).drop(columns='DISTRIBUIDOR'))
        self.assertTrue(self.env['build'](pd.DataFrame([self.row(DISTRIBUIDOR='OTRO')])).empty)
        for n in ['nan','Infinity','1e309',True]:self.assertIsNone(self.env['num'](n))
        self.assertEqual(self.env['num']('1.234,50'),1234.5)
        self.assertTrue(self.env['auto'](SimpleNamespace(census=0,weekly=None)))
        self.assertTrue(self.env['auto'](SimpleNamespace(census=1.5,weekly=.5)))
        self.assertTrue(self.env['auto'](SimpleNamespace(census=.5,weekly=1.5)))
        self.assertFalse(self.env['auto'](SimpleNamespace(census=1.51,weekly=.5)))
        self.assertFalse(self.env['auto'](SimpleNamespace(census=.5,weekly=1.51)))
        self.assertFalse(self.env['auto'](SimpleNamespace(census=-.25,weekly=-.25)))

    def test_refresh_existing_session_for_reported_cases(self):
        d=pd.DataFrame([{'id':'3747','census':1.,'weekly':0.},
                        {'id':'5183','census':1.,'weekly':.38},
                        {'id':'manual','census':1.,'weekly':0.}])
        state={'3747':{'ok':False,'src':None,'corr':None},
               '5183':{'ok':False,'src':'manual','corr':None},
               'manual':{'ok':False,'src':'manual','corr':2.}}
        self.assertTrue(self.env['_refresh_automatic'](d,state))
        for rid in ['3747','5183']:
            self.assertTrue(state[rid]['ok'])
            self.assertEqual(state[rid]['src'],'auto')
        self.assertEqual(state['manual']['corr'],2.)
        self.assertFalse(state['manual']['ok'])
        self.assertFalse(self.env['_refresh_automatic'](d,state))

    def test_schema_drift_fails_closed(self):
        from sales_snapshot import validate_census_schema,DATA
        mapping=json.loads((DATA/'census_schema.json').read_text(encoding='utf-8'))
        cols=['']*max(mapping.values())
        for field,index in mapping.items():cols[index-1]=field
        validate_census_schema(cols)
        with self.assertRaises(ValueError):validate_census_schema(['new']+cols)

    def test_failed_save_keeps_explicit_changes_for_retry(self):
        e=app_functions();pending={'ok':False,'src':None,'corr':None}
        session={'s':{'r':{'ok':False,'src':'manual','corr':2}},'dirty_f':{'reset':pending}}
        e.update(st=SimpleNamespace(session_state=session),sk='s',fp='f',folder_id='test',time=time,persist_msg_key='msg',persist_err_key='err')
        def failure(*args):raise RuntimeError('offline')
        e['save_review_state_drive']=failure
        e['persist_review_state_now']('r')
        self.assertEqual(set(session['dirty_f']),{'r','reset'})
        received=[]
        e['save_review_state_drive']=lambda folder,state,ids:received.append((dict(state),set(ids)))
        e['persist_review_state_now']('r')
        self.assertEqual(received[0][0]['reset'],pending)
        self.assertEqual(session['dirty_f'],{})
        self.assertNotIn('err',session)


if __name__=='__main__':unittest.main()
