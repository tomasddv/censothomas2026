"""Validate the generated app, not just its bootstrap wrapper."""
import ast
import subprocess
import unittest
import pandas as pd
from pathlib import Path


class GeneratedSourceTest(unittest.TestCase):
    def test_generated_app_compiles_and_exports_one_code_per_line(self):
        source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        url = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'BASE_APP_URL' for t in n.targets))
        ref = ast.literal_eval(url.value).split('/')[-2]
        base = subprocess.check_output(['git', 'show', f'{ref}:app.py'], cwd=Path(__file__).parent).decode('utf-8')
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'_replace_once', '_optimized_source'}]
        scope = {'_load_base_app': lambda: base}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'bootstrap', 'exec'), scope)
        generated = scope['_optimized_source']()
        compile(generated, 'ddv_censo_v2', 'exec')
        parsed = ast.parse(generated)
        assignment = next(n for n in ast.walk(parsed) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_codigos' for t in n.targets))
        separator = ast.literal_eval(assignment.value.func.value)
        self.assertEqual(separator.join(['1', '2571']), '1\n2571')
        helper = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == '_latest_available_clients')
        env = {'pd': pd, 'DIST': 'DISTRIBUIDORA DEL VALLE S.A.', 'client_code': str}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'available', 'exec'), env)
        rows = pd.DataFrame([
            {'account_id':'1', 'DISTRIBUIDOR':' DISTRIBUIDORA DEL VALLE S.A. ', 'ESTADO_TAREA':'AVAILABLE', 'FECHA_TAREA':'2026-09-20'},
            {'account_id':'2', 'DISTRIBUIDOR':'OTRO DISTRIBUIDOR', 'ESTADO_TAREA':'AVAILABLE', 'FECHA_TAREA':'2026-09-20'},
            {'account_id':'3', 'DISTRIBUIDOR':None, 'ESTADO_TAREA':'AVAILABLE', 'FECHA_TAREA':'2026-09-20'},
            {'account_id':'4', 'DISTRIBUIDOR':'distribuidora del valle s.a.', 'ESTADO_TAREA':'AVAILABLE', 'FECHA_TAREA':'2026-09-20'},
            {'account_id':'5', 'DISTRIBUIDOR':'DISTRIBUIDORA DEL VALLE S.A.', 'ESTADO_TAREA':'AVAILABLE', 'FECHA_TAREA':'2026-09-19'},
            {'account_id':'5', 'DISTRIBUIDOR':'DISTRIBUIDORA DEL VALLE S.A.', 'ESTADO_TAREA':'COMPLETED', 'FECHA_TAREA':'2026-09-20'},
        ])
        available = env['_latest_available_clients']
        self.assertEqual(set(available(rows)['_client_key']), {'1','4'})
        self.assertTrue(available(rows.drop(columns='DISTRIBUIDOR')).empty)
        self.assertTrue(available(rows.iloc[0:0]).empty)


if __name__ == '__main__':
    unittest.main()
