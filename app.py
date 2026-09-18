from __future__ import annotations

import textwrap
import traceback
import urllib.request

import streamlit as st

# IMPORTANT: page config must be the first Streamlit command.
st.set_page_config(page_title='Revisión Censo DDV', page_icon='✅', layout='wide')

BASE_APP_URL = (
    'https://raw.githubusercontent.com/tomasddv/censothomas2026/'
    '0d5d763c47d89dbd2e414fb3d659d1a6aeafffa0/app.py'
)


@st.cache_data(show_spinner=False, ttl=86400)
def _load_base_app() -> str:
    req = urllib.request.Request(BASE_APP_URL, headers={'User-Agent': 'DDV-Censo/2.0'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode('utf-8')


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f'No pude aplicar el ajuste: {label}')
    return source.replace(old, new, 1)


def _optimized_source() -> str:
    src = _load_base_app()

    # The bootstrap already configured the page. Avoid a second set_page_config.
    src = _replace_once(
        src,
        "st.set_page_config(page_title='Revisión Censo DDV',page_icon='✅',layout='wide')\n",
        '',
        'set_page_config duplicado',
    )

    # Automatic OK rules:
    # 1) censado = 0.25 and venta promedio semanal < 0.25
    # 2) censado = 0 and venta promedio semanal = 0
    # 3) diferencia absoluta entre censado y venta promedio semanal = 0.50
    #    (vale tanto +0.50 como -0.50)
    src = _replace_once(
        src,
        "def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and abs(float(r.census)-.25)<1e-9 and float(r.weekly)<.25",
        "def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and ((abs(float(r.census)-.25)<1e-9 and float(r.weekly)<.25) or (abs(float(r.census))<1e-9 and abs(float(r.weekly))<1e-9) or abs(abs(float(r.census)-float(r.weekly))-.50)<1e-9)",
        'reglas de OK automático',
    )

    # Avoid reparsing Excel files repeatedly inside one session/cache lifecycle.
    src = _replace_once(
        src,
        'def read_censo(b,name):',
        '@st.cache_data(show_spinner=False)\ndef read_censo(b,name):',
        'cache de lectura Excel',
    )
    src = _replace_once(
        src,
        'def combine_censo_files(files):',
        '@st.cache_data(show_spinner=False)\ndef combine_censo_files(files):',
        'cache de combinación',
    )

    # Count clients whose latest ON/OFF task is still AVAILABLE.
    available_helper = r'''def available_clients_count(df):
    if df is None or df.empty or 'account_id' not in df.columns or 'ESTADO_TAREA' not in df.columns:
        return 0
    a=df.copy()
    a['_client_key']=a['account_id'].map(client_code)
    a=a[a['_client_key'].astype(str).str.strip().ne('')]
    if a.empty:return 0
    keys=['_client_key']
    if 'Tipo_Encuesta' in a.columns:keys.append('Tipo_Encuesta')
    if 'FECHA_TAREA' in a.columns:a['_task_date']=pd.to_datetime(a['FECHA_TAREA'],errors='coerce')
    else:a['_task_date']=pd.NaT
    if '__source_order' not in a.columns:a['__source_order']=0
    a=a.sort_values(['_task_date','__source_order'],na_position='first').drop_duplicates(keys,keep='last')
    is_available=a['ESTADO_TAREA'].astype(str).str.strip().str.upper().eq('AVAILABLE')
    return int(a.loc[is_available,'_client_key'].nunique())

'''
    src = _replace_once(src, 'def build(d):\n', available_helper + 'def build(d):\n', 'contador AVAILABLE')

    # Vectorized state enrichment.
    old_enriched = """def enriched(d,state):
    z=d.copy();z['OK']=z.id.map(lambda x:state[x]['ok']);z['Corrección']=z.id.map(lambda x:state[x]['corr']);z['Estado']=z.id.map(lambda x:status(state[x]));z['Valor final']=z.apply(lambda r:r.census if state[r.id]['ok'] else state[r.id]['corr'],axis=1);return z
"""
    new_enriched = """def enriched(d,state):
    z=d.copy();ids=z['id'].tolist();census=z['census'].tolist()
    z['OK']=[state[x]['ok'] for x in ids]
    z['Corrección']=[state[x]['corr'] for x in ids]
    z['Estado']=[status(state[x]) for x in ids]
    z['Valor final']=[c if state[x]['ok'] else state[x]['corr'] for x,c in zip(ids,census)]
    return z
"""
    src = _replace_once(src, old_enriched, new_enriched, 'enriquecimiento rápido')

    # Prepare and cache the expensive parsed/crossed DataFrame once per exact source file set.
    old_prepare = """try:
    combined=combine_censo_files(files)
except Exception as e:
    st.error(f'No pude leer los Excel de respuestas: {type(e).__name__}: {e}')
    st.stop()
try:
    d=build(combined)
except Exception as e:
    st.error(f'No pude cruzar las respuestas con clientes/ventas: {type(e).__name__}: {e}')
    st.stop()
if d.empty:st.warning('No encontré campos de revisión para DDV.');st.stop()
h=hashlib.sha256()
for name,b in files:h.update(name.encode('utf-8'));h.update(b)
fp=h.hexdigest()[:12];sk='state_'+fp
"""
    new_prepare = """h=hashlib.sha256()
for name,b in files:
    h.update(name.encode('utf-8'));h.update(b)
fp=h.hexdigest()[:12]
_data_key='prepared_data_'+fp
if _data_key not in st.session_state:
    try:
        combined=combine_censo_files(files)
    except Exception as e:
        st.error(f'No pude leer los Excel de respuestas: {type(e).__name__}: {e}')
        st.stop()
    try:
        d=build(combined)
        available_count=available_clients_count(combined)
    except Exception as e:
        st.error(f'No pude cruzar las respuestas con clientes/ventas: {type(e).__name__}: {e}')
        st.stop()
    st.session_state[_data_key]=(d,available_count)
else:
    d,available_count=st.session_state[_data_key]
if d.empty:st.warning('No encontré campos de revisión para DDV.');st.stop()
sk='state_'+fp
"""
    src = _replace_once(src, old_prepare, new_prepare, 'preparación única de datos')

    # Reset must also invalidate any prepared export.
    src = _replace_once(
        src,
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={}\n    for k in list(st.session_state):",
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={};st.session_state.pop('prepared_excel_'+fp,None)\n    for k in list(st.session_state):",
        'reinicio',
    )

    # Top KPIs at client level, plus AVAILABLE clients still to be completed.
    old_metrics = """z=enriched(d,state);done=z[z.Estado!='Pendiente'];pend=z[z.Estado=='Pendiente']
a,b,c,d1=st.columns(4);a.metric('Campos',len(z));b.metric('OK',int(z.OK.sum()));c.metric('Corregidos',int(z['Corrección'].notna().sum()));d1.metric('Pendientes',len(pend))
"""
    new_metrics = """z=enriched(d,state);done=z[z.Estado!='Pendiente'];pend=z[z.Estado=='Pendiente']
_client_status=z.groupby('client',dropna=False).agg(
    pendientes=('Estado',lambda s:(s=='Pendiente').any()),
    todos_ok=('OK','all'),
    alguna_corr=('Corrección',lambda s:s.notna().any())
)
_clients_total=int(len(_client_status))
_clients_pending=int(_client_status['pendientes'].sum())
_clients_ok=int((~_client_status['pendientes'] & _client_status['todos_ok']).sum())
_clients_corrected=int((~_client_status['pendientes'] & _client_status['alguna_corr']).sum())
a,b,c,d1,e1=st.columns(5)
a.metric('Clientes a revisar',_clients_total)
b.metric('Clientes OK',_clients_ok)
c.metric('Clientes corregidos',_clients_corrected)
d1.metric('Clientes pendientes',_clients_pending)
e1.metric('Faltan completar',available_count,help='Clientes cuyo último estado de tarea figura como AVAILABLE en las respuestas.')
"""
    src = _replace_once(src, old_metrics, new_metrics, 'KPIs por cliente')

    # Generate the heavy Excel only on demand.
    old_downloads = """x1,x2=st.columns(2);x1.download_button('⬇ Descargar corrección CSV',export(done).to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'correccion_censo_ddv.csv','text/csv',use_container_width=True);x2.download_button('⬇ Descargar corrección Excel',excel(done,pend),'correccion_censo_ddv.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
"""
    new_downloads = """x1,x2=st.columns(2)
x1.download_button('⬇ Descargar corrección CSV',export(done).to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'correccion_censo_ddv.csv','text/csv',use_container_width=True)
_excel_key='prepared_excel_'+fp
if x2.button('Preparar Excel actualizado',key='prep_excel_'+fp,use_container_width=True):
    with st.spinner('Preparando Excel…'):
        st.session_state[_excel_key]=excel(done,pend)
if _excel_key in st.session_state:
    x2.download_button('⬇ Descargar Excel',st.session_state[_excel_key],'correccion_censo_ddv.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True,key='download_excel_'+fp)
"""
    src = _replace_once(src, old_downloads, new_downloads, 'Excel bajo demanda')

    # Faster default page; fewer widgets per run.
    src = _replace_once(
        src,
        "size=st.selectbox('Filas por página',[25,50,100],index=1)",
        "size=st.selectbox('Filas por página',[10,25,50,100],index=1)",
        'paginación',
    )

    # Only keep real undo grace-period rows inside No OK.
    src = _replace_once(
        src,
        "elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]",
        "elif okf=='No OK':\n    _active_holds={rid for rid,ts in holds.items() if time.time()-ts<=UNDO_SECONDS}\n    f=f[(~f.OK)|f.id.isin(_active_holds)]",
        'filtro No OK',
    )

    # Text correction invalidates a previously prepared export.
    src = _replace_once(
        src,
        "if not v:x['corr']=None;return",
        "if not v:x['corr']=None;st.session_state.pop('prepared_excel_'+fp,None);return",
        'borrar corrección',
    )
    src = _replace_once(
        src,
        "x['corr']=n;x['src']='manual'",
        "x['corr']=n;x['src']='manual';st.session_state.pop('prepared_excel_'+fp,None)",
        'guardar corrección',
    )

    # OK actions are callbacks: one rerun instead of click + explicit second rerun.
    old_actions = """def mark_ok(rid):
    x=state[rid]
    if x['corr'] is not None:return
    x['ok']=True;x['src']='manual';holds[rid]=time.time();st.rerun()

def undo_ok(rid):
    x=state[rid]
    if x.get('src')=='auto':return
    x['ok']=False;x['src']=None;holds.pop(rid,None);st.rerun()
"""
    new_actions = """def mark_ok(rid):
    x=st.session_state[sk][rid]
    if x['corr'] is not None:return
    x['ok']=True;x['src']='manual';st.session_state[hold_key][rid]=time.time();st.session_state.pop('prepared_excel_'+fp,None)

def undo_ok(rid):
    x=st.session_state[sk][rid]
    if x.get('src')=='auto':return
    x['ok']=False;x['src']=None;st.session_state[hold_key].pop(rid,None);st.session_state.pop('prepared_excel_'+fp,None)
"""
    src = _replace_once(src, old_actions, new_actions, 'callbacks OK')

    src = _replace_once(
        src,
        "if co[6].button('✅ OK',key=f'ok_{fp}_{r.id}',type='primary',use_container_width=True):undo_ok(r.id)",
        "co[6].button('✅ OK',key=f'ok_{fp}_{r.id}',type='primary',use_container_width=True,on_click=undo_ok,args=(r.id,))",
        'botón deshacer OK',
    )
    src = _replace_once(
        src,
        "if co[6].button('OK',key=f'ok_{fp}_{r.id}',disabled=x['corr'] is not None,use_container_width=True):mark_ok(r.id)",
        "co[6].button('OK',key=f'ok_{fp}_{r.id}',disabled=x['corr'] is not None,use_container_width=True,on_click=mark_ok,args=(r.id,))",
        'botón marcar OK',
    )

    return src


try:
    _src = _optimized_source()
    exec(compile(_src, 'ddv_censo_v2', 'exec'), globals(), globals())
except Exception as exc:
    st.error(f'No pude iniciar la aplicación: {type(exc).__name__}: {exc}')
    with st.expander('Detalle técnico'):
        st.code(traceback.format_exc())
    st.stop()
