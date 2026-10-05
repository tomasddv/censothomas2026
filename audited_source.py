"""Audited corrections applied to the legacy generated UI without changing its layout."""
import ast
import textwrap
import json
from pathlib import Path


def replace_function(source, name, replacement):
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = source.splitlines(keepends=True)
    # Keep existing Streamlit cache decorators.
    lines[node.lineno-1:node.end_lineno] = [textwrap.dedent(replacement).strip()+'\n']
    return ''.join(lines)


def apply_audit_fixes(src):
    revision=json.loads((Path(__file__).parent/'data/sales_manifest.json').read_text(encoding='utf-8'))['data_sha256'][:16]
    def change(old, new):
        nonlocal src
        if old not in src:
            raise ValueError('No se pudo aplicar un control de auditoría: '+old[:75])
        src = src.replace(old,new)

    src = replace_function(src,'lookups','''
def lookups():
    from sales_snapshot import load_sales_snapshot
    c=pd.read_csv(_decode_lookup(CLIENT_LOOKUP_B64,'clientes/promotores'),dtype={'client':str})
    if c.client.duplicated().any():raise ValueError('Padrón con clientes duplicados')
    s=load_sales_snapshot()
    return c.set_index('client',drop=False),s.set_index(['client','product'],drop=False)
''')
    src = replace_function(src,'num','''
def num(v):
    if v is None or isinstance(v,bool) or pd.isna(v):return None
    s=str(v).strip().replace(' ','')
    if not s:return None
    if ',' in s and '.' in s:s=s.replace('.','').replace(',','.') if s.rfind(',')>s.rfind('.') else s.replace(',','')
    else:s=s.replace(',','.')
    try:
        n=float(s)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None
''')
    change("d.columns=[str(c).strip() for c in d.columns]", "d.columns=[str(c).strip() for c in d.columns]\n    from sales_snapshot import validate_census_schema\n    validate_census_schema(d.columns)")
    change("w=d.copy()\n    if 'DISTRIBUIDOR' in w:w=w[w.DISTRIBUIDOR.astype(str).str.strip().eq(DIST)]",
           "w=d.copy()\n    if 'DISTRIBUIDOR' not in w:raise ValueError('Falta DISTRIBUIDOR; no se puede asegurar la población DDV')\n    w=w[w.DISTRIBUIDOR.astype(str).str.strip().str.casefold().eq(DIST.casefold())]\n    w=w.copy()\n    w['_client_audit']=w['account_id'].map(client_code)\n    w['_date_audit']=pd.to_datetime(w['FECHA_TAREA'],errors='coerce') if 'FECHA_TAREA' in w else pd.NaT\n    if '__source_order' not in w:w['__source_order']=0\n    keys=['_client_audit']+(['Tipo_Encuesta'] if 'Tipo_Encuesta' in w else [])\n    w=w.sort_values(['_date_audit','__source_order'],na_position='first').drop_duplicates(keys,keep='last')")
    change("if si is None:\n                get=lambda k,default=None: (0.0 if k in {'weeklyPacks','monthlyBultos','jun','jul','aug'} else ('Sin movimientos en ventas' if k=='coverage' else default))",
           "if si is None:\n                reason='Presentación sin equivalencia validada' if p in {'1200cc','1 litro OW'} else 'Cliente sin cruce en archivo de ventas'\n                get=lambda k,default=None: reason if k=='coverage' else default")
    change("def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and abs(float(r.census)-float(r.weekly))<=.50+1e-9",
           "def auto(r):return pd.isna(r.weekly) or (num(r.census) is not None and num(r.weekly) is not None and float(r.census)>=0 and float(r.weekly)>=0 and abs(float(r.census)-float(r.weekly))<=1.0+1e-9)")
    # Normalize accented question/brand text before matching.
    change("s=txt(v).upper();o=set()", "s=unicodedata.normalize('NFKD',txt(v)).encode('ascii','ignore').decode().upper();o=set()")
    change("u=q.upper().replace('CLÁSICA','CLASICA')", "u=unicodedata.normalize('NFKD',q).encode('ascii','ignore').decode().upper()")
    change("prepared_data_v7_sales5442_", "prepared_data_audit_20261001_")
    start=src.index("if not st.session_state.get('sales5442_refreshed_'+fp):")
    end=src.index("hold_key='ok_hold_'+fp",start)
    src=src[:start]+'''def _refresh_automatic(d,state):
    changed=False
    for r in d.itertuples():
        x=state.setdefault(r.id,{'ok':False,'src':None,'corr':None})
        if x.get('corr') is not None or (x.get('src')=='manual' and x.get('ok')):
            continue
        approved=bool(auto(r))
        origin='auto' if approved else None
        if x.get('ok')!=approved or x.get('src')!=origin:
            x['ok']=approved;x['src']=origin;changed=True
    return changed

if _refresh_automatic(d,state):
    st.session_state.pop('prepared_excel_'+fp,None)

'''+src[end:]
    # Restoring saved human decisions must never be overridden by new automatic values.
    change("if _rid not in _base_state or _base_state[_rid].get('src')=='auto':", "if _rid not in _base_state:")
    change("            save_review_state_drive(folder_id,_base_state)\n", "")
    # Imports for pure, tested merging helpers; dirty patches preserve records outside this census.
    change("REVIEW_STATE_FILE='revision_censo_ddv_estado.json'", "from review_state import merge_review_records, restore_manual\nREVIEW_STATE_FILE='revision_censo_ddv_estado.json'")
    start=src.index('            for _rid,_sx in _saved.items():')
    end=src.index('            st.session_state[persist_msg_key]',start)
    src=src[:start]+"            _base_state=restore_manual(_base_state,_saved)\n"+src[end:]
    change("def save_review_state_drive(folder_id,state):", "def save_review_state_drive(folder_id,state,changed_ids=None):")
    start=src.index('    records={}\n',src.index('def save_review_state_drive'))
    end=src.index('    payload={',start)
    src=src[:start]+"    records=merge_review_records(load_review_state_drive(folder_id),state,changed_ids or [])\n"+src[end:]
    # Only explicitly modified IDs are persisted. A failed save retains the dirty set for retry.
    src=replace_function(src,'persist_review_state_now','''
def persist_review_state_now(rid):
    dirty=st.session_state.setdefault('dirty_'+fp,{})
    dirty[rid]=dict(st.session_state[sk][rid])
    try:
        save_review_state_drive(folder_id,dirty,set(dirty))
        dirty.clear()
        st.session_state[persist_msg_key]='Guardado '+time.strftime('%H:%M:%S')
        st.session_state.pop(persist_err_key,None)
    except Exception as e:
        st.session_state[persist_err_key]=str(e)
''')
    change('persist_review_state_now();','persist_review_state_now(rid);')
    change('persist_review_state_now()\n','persist_review_state_now(rid)\n')
    change("if not v:x['corr']=None;", "if not v:x['corr']=None;x['src']=None;")
    change('save_review_state_drive(folder_id,st.session_state[sk])', "save_review_state_drive(folder_id,st.session_state.get('dirty_'+fp,{}),set(st.session_state.get('dirty_'+fp,{})));st.session_state['dirty_'+fp]={}")
    # A reset deliberately clears only the currently displayed census records.
    change("st.session_state[sk]=fresh(d);st.session_state[hold_key]={};", "st.session_state['dirty_'+fp]={rid:{'ok':False,'src':None,'corr':None} for rid in d.id};st.session_state[sk]=fresh(d);st.session_state[hold_key]={};")
    # Explicit scope and definitions beside the numbers and in every export.
    change("st.caption('Drive → cruce de ventas → revisión por promotor → descarga de correcciones')",
           "st.caption('Compras al distribuidor: junio–agosto 2026 · bultos. Promedio mensual = total / 3; semanal = total × 7 / 92 días. El censo declara ventas del comercio, por lo que la comparación es una referencia.')")
    change("Sin ventas registradas para esos SKUs se toma Venta = 0.", "Sin cruce o presentación validada se muestra N/D y se marca OK automático por criterio de revisión. Cero significa sin movimientos de ese producto para un cliente identificado en el archivo.")
    change("if v is None or pd.isna(v):return '—'", "if v is None or pd.isna(v):return 'N/D'")
    change("st.write(f'**Pregunta:** {r.field}');st.write(f'**Ventas:", "st.write(f'**Pregunta:** {r.field}');st.write(f'**Cruce:** {r.coverage}');st.write(f'**Ventas:")
    change("return z[cols].rename(columns=dict(zip(cols,names)))", "out=z[cols].rename(columns=dict(zip(cols,names))).copy()\n    out['Unidad']=z['unit'].values\n    out['Período ventas']='Junio–agosto 2026 (92 días)'\n    out['Fuente ventas']='trimestre bultos.txt'\n    return out")
    change("'⬇ Descargar corrección CSV'", "'⬇ Descargar todas las correcciones CSV'")
    change("'Preparar Excel actualizado'", "'Preparar Excel completo actualizado'")
    change("a.metric('Clientes a revisar'", "a.metric('Clientes a revisar · total'")
    change('def lookups():',f'def lookups(sales_revision={revision!r}):')
    change('prepared_data_audit_20261001_',f'prepared_data_audit_{revision}_')
    change("st.sidebar.caption('OK automático: diferencia absoluta entre Censado y Venta prom./sem. ≤ 0,50.')", "st.sidebar.caption('OK automático: diferencia absoluta ≤ 0,50 o venta N/D. Las correcciones manuales se conservan.')")
    change('≤ 0,50', '≤ 1,00')
    compile(src,'ddv_censo_audit','exec')
    return src
