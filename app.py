from __future__ import annotations

import textwrap
import traceback
import urllib.request
import json

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

    # Automatic OK: cualquier diferencia absoluta entre censado y venta semanal
    # menor o igual a 0.50 queda aprobada automáticamente.
    src = _replace_once(
        src,
        "def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and abs(float(r.census)-.25)<1e-9 and float(r.weekly)<.25",
        "def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and abs(float(r.census)-float(r.weekly))<=.50+1e-9",
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

    # AVAILABLE: detalle por cliente, total y resumen por promotor.
    available_helper = r'''def _latest_available_clients(df):
    cols=['_client_key','account_id','FECHA_TAREA','Tipo_Encuesta','DISTRIBUIDOR']
    if df is None or df.empty or 'account_id' not in df.columns or 'ESTADO_TAREA' not in df.columns:
        return pd.DataFrame(columns=cols)
    if 'DISTRIBUIDOR' not in df.columns:
        return pd.DataFrame(columns=cols)
    a=df.loc[df['DISTRIBUIDOR'].astype(str).str.strip().str.casefold().eq(DIST.casefold())].copy()
    a['_client_key']=a['account_id'].map(client_code)
    a=a[a['_client_key'].astype(str).str.strip().ne('')]
    if a.empty:return pd.DataFrame(columns=cols)
    keys=['_client_key']
    if 'Tipo_Encuesta' in a.columns:keys.append('Tipo_Encuesta')
    if 'FECHA_TAREA' in a.columns:a['_task_date']=pd.to_datetime(a['FECHA_TAREA'],errors='coerce')
    else:a['_task_date']=pd.NaT
    if '__source_order' not in a.columns:a['__source_order']=0
    a=a.sort_values(['_task_date','__source_order'],na_position='first').drop_duplicates(keys,keep='last')
    is_available=a['ESTADO_TAREA'].astype(str).str.strip().str.upper().eq('AVAILABLE')
    a=a.loc[is_available].copy()
    if a.empty:return pd.DataFrame(columns=cols)
    a=a.sort_values(['_task_date','__source_order'],na_position='first').drop_duplicates('_client_key',keep='last')
    for col in cols:
        if col not in a.columns:a[col]=''
    return a[cols]

def available_clients_detail(df):
    a=_latest_available_clients(df)
    columns=['Código cliente','Account ID','Nombre','Promotor','Supervisor','Fecha tarea','Encuesta','Distribuidor']
    if a.empty:return pd.DataFrame(columns=columns)
    c,_=lookups()
    rows=[]
    for _,r in a.iterrows():
        cli=txt(r.get('_client_key'))
        prom='Sin promotor asignado'
        sup='Sin supervisor asignado'
        name='Nombre no disponible'
        if cli in c.index:
            ci=c.loc[cli]
            if isinstance(ci,pd.DataFrame):ci=ci.iloc[0]
            prom=txt(ci.get('promotor')) or prom
            sup=txt(ci.get('supervisor')) or sup
            name=txt(ci.get('name')) or name
        rows.append({
            'Código cliente':cli,
            'Account ID':txt(r.get('account_id')),
            'Nombre':name,
            'Promotor':prom,
            'Supervisor':sup,
            'Fecha tarea':txt(r.get('FECHA_TAREA'))[:10],
            'Encuesta':txt(r.get('Tipo_Encuesta')),
            'Distribuidor':txt(r.get('DISTRIBUIDOR'))
        })
    return pd.DataFrame(rows,columns=columns).sort_values(['Supervisor','Promotor','Nombre','Código cliente']).reset_index(drop=True)

def available_clients_count(df):
    return int(len(available_clients_detail(df)))

def available_clients_by_promotor(df):
    b=available_clients_detail(df)
    if b.empty:
        return pd.DataFrame(columns=['supervisor','promotor','Clientes AVAILABLE'])
    return b.groupby(['Supervisor','Promotor'],dropna=False)['Código cliente'].nunique().reset_index().rename(
        columns={'Supervisor':'supervisor','Promotor':'promotor','Código cliente':'Clientes AVAILABLE'}
    )

REVIEW_STATE_FILE='revision_censo_ddv_estado.json'

def _drive_service_review_rw():
    if not has_service_account():
        raise RuntimeError('No hay cuenta de servicio configurada.')
    from google.oauth2 import service_account
    from googleapiclient.discovery import build as google_build
    info=dict(st.secrets['gcp_service_account'])
    creds=service_account.Credentials.from_service_account_info(
        info,
        scopes=['https://www.googleapis.com/auth/drive'],
    )
    return google_build('drive','v3',credentials=creds,cache_discovery=False)

def _review_state_file_id(service,folder_id):
    safe=REVIEW_STATE_FILE.replace("'","\'")
    q=f"'{folder_id}' in parents and trashed = false and name = '{safe}'"
    res=service.files().list(
        q=q,
        fields='files(id,name,modifiedTime)',
        pageSize=20,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        orderBy='modifiedTime desc',
    ).execute()
    files=res.get('files',[])
    return files[0]['id'] if files else None

def load_review_state_drive(folder_id):
    if not has_service_account():return {}
    from googleapiclient.http import MediaIoBaseDownload
    service=_drive_service_review_rw()
    fid=_review_state_file_id(service,folder_id)
    if not fid:return {}
    req=service.files().get_media(fileId=fid,supportsAllDrives=True)
    bio=io.BytesIO();downloader=MediaIoBaseDownload(bio,req,chunksize=256*1024)
    done=False
    while not done:_,done=downloader.next_chunk()
    raw=bio.getvalue().decode('utf-8').strip()
    if not raw:return {}
    obj=json.loads(raw)
    return obj.get('records',obj) if isinstance(obj,dict) else {}

def save_review_state_drive(folder_id,state):
    if not has_service_account():
        raise RuntimeError('No hay cuenta de servicio configurada.')
    from googleapiclient.http import MediaIoBaseUpload
    records={}
    for rid,x in state.items():
        corr=x.get('corr')
        src=x.get('src')
        if src=='manual' or corr is not None:
            records[str(rid)]={
                'ok':bool(x.get('ok',False)),
                'src':'manual',
                'corr':None if corr is None else float(corr),
            }
    payload={
        'version':1,
        'updated_at':time.strftime('%Y-%m-%d %H:%M:%S'),
        'records':records,
    }
    data=json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8')
    service=_drive_service_review_rw()
    media=MediaIoBaseUpload(io.BytesIO(data),mimetype='application/json',resumable=False)
    fid=_review_state_file_id(service,folder_id)
    if not fid:
        raise RuntimeError(
            'No existe revision_censo_ddv_estado.json en la carpeta de Drive. '
            'Subilo una sola vez desde tu cuenta de Google; después la app lo actualizará automáticamente.'
        )
    service.files().update(
        fileId=fid,
        media_body=media,
        supportsAllDrives=True,
    ).execute()
    return len(records)

'''
    src = _replace_once(src, 'def build(d):\n', available_helper + 'def build(d):\n', 'contador AVAILABLE')

    # Si el cliente/producto no tiene fila en el cruce de ventas, significa que no hubo
    # movimientos de esos SKUs en el período. Mostrar 0 en lugar de un guion.
    old_missing_sales = """            si=s.loc[(cli,prod)] if (cli,prod) in s.index else None
            if isinstance(si,pd.DataFrame):si=si.iloc[0]
            get=lambda k,default=None: default if si is None or pd.isna(si.get(k,default)) else si.get(k,default)
"""
    new_missing_sales = """            si=s.loc[(cli,prod)] if (cli,prod) in s.index else None
            if isinstance(si,pd.DataFrame):si=si.iloc[0]
            if si is None:
                get=lambda k,default=None: (0.0 if k in {'weeklyPacks','monthlyBultos','jun','jul','aug'} else ('Sin movimientos en ventas' if k=='coverage' else default))
            else:
                get=lambda k,default=None: default if pd.isna(si.get(k,default)) else si.get(k,default)
"""
    src = _replace_once(src, old_missing_sales, new_missing_sales, 'ventas faltantes como cero')

    src = _replace_once(
        src,
        "st.sidebar.caption('OK automático: solo Censado = 0,25 y Venta prom./sem. < 0,25.')",
        "st.sidebar.caption('OK automático: diferencia absoluta entre Censado y Venta prom./sem. ≤ 0,50.')",
        'texto regla OK sidebar',
    )
    src = _replace_once(
        src,
        "st.caption('Todo caso distinto de Censado 0,25 + Venta semanal menor a 0,25 queda para revisión manual.')",
        "st.caption('OK automático cuando la diferencia absoluta entre Censado y Venta prom./sem. es ≤ 0,50. Sin ventas registradas para esos SKUs se toma Venta = 0.')",
        'texto regla OK final',
    )

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
_data_key='prepared_data_v6_sales3371_'+fp
if _data_key not in st.session_state:
    try:
        combined=combine_censo_files(files)
    except Exception as e:
        st.error(f'No pude leer los Excel de respuestas: {type(e).__name__}: {e}')
        st.stop()
    try:
        d=build(combined)
        available_detail=available_clients_detail(combined)
        available_count=int(len(available_detail))
        available_by_promotor=(
            available_detail.groupby(['Supervisor','Promotor'],dropna=False)['Código cliente']
            .nunique().reset_index()
            .rename(columns={'Supervisor':'supervisor','Promotor':'promotor','Código cliente':'Clientes AVAILABLE'})
            if not available_detail.empty else
            pd.DataFrame(columns=['supervisor','promotor','Clientes AVAILABLE'])
        )
    except Exception as e:
        st.error(f'No pude cruzar las respuestas con clientes/ventas: {type(e).__name__}: {e}')
        st.stop()
    st.session_state[_data_key]=(d,available_count,available_by_promotor,available_detail)
else:
    d,available_count,available_by_promotor,available_detail=st.session_state[_data_key]
if d.empty:st.warning('No encontré campos de revisión para DDV.');st.stop()
sk='state_'+fp
"""
    src = _replace_once(src, old_prepare, new_prepare, 'preparación única de datos')

    # Load manual OK/corrections from Drive once per source fingerprint.
    old_state_init = """if sk not in st.session_state:st.session_state[sk]=fresh(d)
state=st.session_state[sk]
hold_key='ok_hold_'+fp
"""
    new_state_init = """persist_msg_key='persist_msg_'+fp
persist_err_key='persist_err_'+fp
if sk not in st.session_state:
    _base_state=fresh(d)
    if has_service_account():
        try:
            _saved=load_review_state_drive(folder_id)
            for _rid,_sx in _saved.items():
                if _rid not in _base_state or _base_state[_rid].get('src')=='auto':
                    continue
                _corr=num(_sx.get('corr')) if isinstance(_sx,dict) else None
                _ok=bool(_sx.get('ok',False)) if isinstance(_sx,dict) else False
                if _corr is not None and _corr>=0:
                    _base_state[_rid]['ok']=False
                    _base_state[_rid]['src']='manual'
                    _base_state[_rid]['corr']=_corr
                elif _ok:
                    _base_state[_rid]['ok']=True
                    _base_state[_rid]['src']='manual'
                    _base_state[_rid]['corr']=None
            save_review_state_drive(folder_id,_base_state)
            st.session_state[persist_msg_key]='Autoguardado en Drive activo.'
            st.session_state.pop(persist_err_key,None)
        except Exception as e:
            st.session_state[persist_err_key]=str(e)
    st.session_state[sk]=_base_state
state=st.session_state[sk]
hold_key='ok_hold_'+fp
if persist_err_key in st.session_state:
    st.sidebar.warning('⚠️ No pude guardar las correcciones en Drive. La carpeta ya puede estar compartida correctamente; verificá que exista el archivo revision_censo_ddv_estado.json dentro de esa carpeta. Detalle: '+st.session_state[persist_err_key][:180])
elif has_service_account():
    st.sidebar.success('💾 Correcciones: guardado automático en Drive')
if st.sidebar.button('💾 Guardar correcciones ahora',use_container_width=True):
    try:
        save_review_state_drive(folder_id,st.session_state[sk])
        st.session_state[persist_msg_key]='Guardado '+time.strftime('%H:%M:%S')
        st.session_state.pop(persist_err_key,None)
        st.sidebar.success('Correcciones guardadas.')
    except Exception as e:
        st.session_state[persist_err_key]=str(e)
        st.sidebar.error('No pude guardar en Drive. Verificá que revision_censo_ddv_estado.json exista en la carpeta y que la cuenta de servicio tenga permiso de Editor.')
"""
    src = _replace_once(src, old_state_init, new_state_init, 'persistencia de correcciones')

    # Reset must also invalidate any prepared export.
    src = _replace_once(
        src,
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={}\n    for k in list(st.session_state):",
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={};st.session_state.pop('prepared_excel_'+fp,None)\n    try:\n        save_review_state_drive(folder_id,st.session_state[sk]);st.session_state[persist_msg_key]='Estado reiniciado y guardado en Drive.';st.session_state.pop(persist_err_key,None)\n    except Exception as e:\n        st.session_state[persist_err_key]=str(e)\n    for k in list(st.session_state):",
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

    # Promotor selector with client counts, plus an explicit summary by promoter.
    old_filters = """f1,f2,f3,f4,f5,f6=st.columns(6)
sup=f1.selectbox('Supervisor',['Todos']+sorted(z.supervisor.unique()));pro=f2.selectbox('Promotor',['Todos']+sorted(z.promotor.unique()));bra=f3.selectbox('Marca',['Todas']+sorted(z.brand.unique()));prd=f4.selectbox('Producto',['Todos']+sorted(z.loc[z['brand'].eq(bra),'product'].unique() if bra!='Todas' else z['product'].unique()));est=f5.selectbox('Estado',['Todos','Pendientes','Completados']);okf=f6.selectbox('OK',['Todos','OK','No OK'])
search=st.text_input('Cliente',placeholder='Código, nombre o account ID')
f=z
if sup!='Todos':f=f[f.supervisor.eq(sup)]
if pro!='Todos':f=f[f.promotor.eq(pro)]
if bra!='Todas':f=f[f.brand.eq(bra)]
if prd!='Todos':f=f[f['product'].eq(prd)]
if est=='Pendientes':f=f[f.Estado.eq('Pendiente')]
elif est=='Completados':f=f[~f.Estado.eq('Pendiente')]
if okf=='OK':f=f[f.OK]
elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]
if search.strip():
    q=search.lower();f=f[f.client.astype(str).str.lower().str.contains(q,regex=False)|f.name.str.lower().str.contains(q,regex=False)|f.account.astype(str).str.lower().str.contains(q,regex=False)]
"""
    new_filters = """f1,f2,f3,f4,f5,f6=st.columns(6)
sup=f1.selectbox('Supervisor',['Todos']+sorted(z.supervisor.unique()))
_prom_base=z if sup=='Todos' else z[z.supervisor.eq(sup)]
_prom_total=_prom_base.groupby('promotor')['client'].nunique()
_prom_pending=_prom_base[_prom_base.Estado.eq('Pendiente')].groupby('promotor')['client'].nunique()

_avail_base=available_by_promotor if sup=='Todos' else available_by_promotor[available_by_promotor['supervisor'].eq(sup)]
_prom_available=_avail_base.groupby('promotor')['Clientes AVAILABLE'].sum() if not _avail_base.empty else pd.Series(dtype='int64')

_all_promoters=sorted(set(_prom_total.index.tolist()) | set(_prom_available.index.tolist()))
_prom_options=['Todos']+_all_promoters

def _prom_label(p):
    if p=='Todos':
        return f"Todos · {int(_prom_base['client'].nunique())} a revisar · {int(_prom_base.loc[_prom_base.Estado.eq('Pendiente'),'client'].nunique())} pendientes · {int(_prom_available.sum())} AVAILABLE"
    return f"{p} · {int(_prom_total.get(p,0))} a revisar · {int(_prom_pending.get(p,0))} pendientes · {int(_prom_available.get(p,0))} AVAILABLE"

pro=f2.selectbox('Promotor',_prom_options,format_func=_prom_label)
bra=f3.selectbox('Marca',['Todas']+sorted(z.brand.unique()))
prd=f4.selectbox('Producto',['Todos']+sorted(z.loc[z['brand'].eq(bra),'product'].unique() if bra!='Todas' else z['product'].unique()))
est=f5.selectbox('Estado',['Todos','Pendientes','Completados'])
okf=f6.selectbox('OK',['Todos','OK','No OK'])

_prom_idx=pd.Index(_all_promoters,name='promotor')
_prom_summary=pd.DataFrame(index=_prom_idx)
_prom_summary['Clientes a revisar']=_prom_total.reindex(_prom_idx,fill_value=0).astype(int)
_prom_summary['Clientes pendientes']=_prom_pending.reindex(_prom_idx,fill_value=0).astype(int)
_prom_summary['Clientes resueltos']=_prom_summary['Clientes a revisar']-_prom_summary['Clientes pendientes']
_prom_summary['Clientes AVAILABLE']=_prom_available.reindex(_prom_idx,fill_value=0).astype(int)
_prom_summary=_prom_summary.reset_index().rename(columns={'promotor':'Promotor'})

with st.expander('📊 Cantidad de clientes por promotor',expanded=False):
    st.dataframe(_prom_summary,hide_index=True,use_container_width=True)

if pro!='Todos':
    st.info(f"📌 {pro}: {int(_prom_available.get(pro,0))} clientes AVAILABLE todavía sin completar.")

with st.expander('📋 Clientes AVAILABLE para seguimiento y descarga',expanded=False):
    _av=available_detail.copy()
    _av1,_av2,_av3=st.columns([1.2,1.5,2])
    _av_sup_opts=['Todos']+sorted(_av['Supervisor'].dropna().astype(str).unique().tolist()) if not _av.empty else ['Todos']
    _av_sup=_av1.selectbox('Supervisor AVAILABLE',_av_sup_opts,key=f'av_sup_{fp}')
    _av_prom_base=_av if _av_sup=='Todos' else _av[_av['Supervisor'].eq(_av_sup)]
    _av_pro_opts=['Todos']+sorted(_av_prom_base['Promotor'].dropna().astype(str).unique().tolist()) if not _av_prom_base.empty else ['Todos']
    _av_pro=_av2.selectbox('Promotor AVAILABLE',_av_pro_opts,key=f'av_pro_{fp}')
    _av_q=_av3.text_input('Buscar AVAILABLE',placeholder='Código, nombre o account ID',key=f'av_search_{fp}')

    _av_f=_av.copy()
    if _av_sup!='Todos':_av_f=_av_f[_av_f['Supervisor'].eq(_av_sup)]
    if _av_pro!='Todos':_av_f=_av_f[_av_f['Promotor'].eq(_av_pro)]
    if _av_q.strip():
        _q=_av_q.strip().lower()
        _av_f=_av_f[
            _av_f['Código cliente'].astype(str).str.lower().str.contains(_q,regex=False) |
            _av_f['Account ID'].astype(str).str.lower().str.contains(_q,regex=False) |
            _av_f['Nombre'].astype(str).str.lower().str.contains(_q,regex=False)
        ]

    st.caption(f"{len(_av_f)} clientes AVAILABLE en el filtro.")
    st.dataframe(_av_f,hide_index=True,use_container_width=True)

    _dl1,_dl2=st.columns(2)
    _dl1.download_button(
        '⬇ Descargar listado AVAILABLE filtrado',
        _av_f.to_csv(index=False,sep=';').encode('utf-8-sig'),
        'clientes_available_filtrados.csv',
        'text/csv',
        use_container_width=True,
        key=f'dl_av_full_{fp}'
    )
    _codigos='\\n'.join(_av_f['Código cliente'].astype(str).tolist())
    _dl2.download_button(
        '⬇ Descargar solo códigos',
        _codigos.encode('utf-8'),
        'codigos_clientes_available.txt',
        'text/plain',
        use_container_width=True,
        key=f'dl_av_codes_{fp}'
    )

search=st.text_input('Cliente',placeholder='Código, nombre o account ID')
f=z
if sup!='Todos':f=f[f.supervisor.eq(sup)]
if pro!='Todos':f=f[f.promotor.eq(pro)]
if bra!='Todas':f=f[f.brand.eq(bra)]
if prd!='Todos':f=f[f['product'].eq(prd)]
if est=='Pendientes':f=f[f.Estado.eq('Pendiente')]
elif est=='Completados':f=f[~f.Estado.eq('Pendiente')]
if okf=='OK':f=f[f.OK]
elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]
if search.strip():
    q=search.lower();f=f[f.client.astype(str).str.lower().str.contains(q,regex=False)|f.name.str.lower().str.contains(q,regex=False)|f.account.astype(str).str.lower().str.contains(q,regex=False)]
"""
    src = _replace_once(src, old_filters, new_filters, 'filtros y resumen por promotor')

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

    # Paginate by CLIENT, not by product/question rows, and show clear page progress.
    old_pagination = """size=st.selectbox('Filas por página',[25,50,100],index=1);pages=max(1,math.ceil(len(f)/size));page=st.number_input('Página',1,pages,1);page_df=f.iloc[(page-1)*size:page*size];st.caption(f'Mostrando {len(f)} de {len(z)}')
"""
    new_pagination = """_client_list=f[['client','name','promotor']].drop_duplicates('client').sort_values(['promotor','name','client']) if not f.empty else f[['client','name','promotor']].drop_duplicates('client')
_filtered_clients=int(len(_client_list))
_filtered_pending=int(f.loc[f.Estado.eq('Pendiente'),'client'].nunique()) if not f.empty else 0
_nav1,_nav2,_nav3=st.columns([1.2,1,3])
size=_nav1.selectbox('Clientes por página',[5,10,15,25,50],index=1,key=f'clients_per_page_{fp}')
pages=max(1,math.ceil(_filtered_clients/size))
_page_key=f'page_clients_{fp}'
if _page_key not in st.session_state:st.session_state[_page_key]=1
if st.session_state[_page_key]>pages:st.session_state[_page_key]=pages
page=int(_nav2.number_input('Página',min_value=1,max_value=pages,step=1,key=_page_key))
_start=(page-1)*size
_end=min(_start+size,_filtered_clients)
_page_clients=_client_list.iloc[_start:_end]['client'].tolist() if _filtered_clients else []
page_df=f[f.client.isin(_page_clients)].copy()
if not page_df.empty:
    page_df['_client_order']=pd.Categorical(page_df['client'],categories=_page_clients,ordered=True)
    page_df=page_df.sort_values(['_client_order','product']).drop(columns=['_client_order'])
_selected_name='Todos los promotores' if pro=='Todos' else pro
_nav3.markdown(f"**{_selected_name}**  \\n{_filtered_clients} clientes en el filtro · {_filtered_pending} con revisión pendiente")
st.info(f"Página {page} de {pages} · mostrando clientes {_start+1 if _filtered_clients else 0} a {_end} de {_filtered_clients}. Cada cliente puede tener más de una pregunta/producto para revisar.")
"""
    src = _replace_once(src, old_pagination, new_pagination, 'paginación por clientes')

    # Only keep real undo grace-period rows inside No OK.
    src = _replace_once(
        src,
        "elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]",
        "elif okf=='No OK':\n    _active_holds={rid for rid,ts in holds.items() if time.time()-ts<=UNDO_SECONDS}\n    f=f[(~f.OK)|f.id.isin(_active_holds)]",
        'filtro No OK',
    )

    # Persist manual changes immediately to Drive.
    persist_helper = """def persist_review_state_now():
    try:
        save_review_state_drive(folder_id,st.session_state[sk])
        st.session_state[persist_msg_key]='Guardado '+time.strftime('%H:%M:%S')
        st.session_state.pop(persist_err_key,None)
    except Exception as e:
        st.session_state[persist_err_key]=str(e)

"""
    src = _replace_once(src, 'def cb_corr(rid,key):\n', persist_helper + 'def cb_corr(rid,key):\n', 'helper de persistencia')

    # Text correction invalidates a previously prepared export.
    src = _replace_once(
        src,
        "if not v:x['corr']=None;return",
        "if not v:x['corr']=None;st.session_state.pop('prepared_excel_'+fp,None);persist_review_state_now();return",
        'borrar corrección',
    )
    src = _replace_once(
        src,
        "x['corr']=n;x['src']='manual'",
        "x['corr']=n;x['src']='manual';st.session_state.pop('prepared_excel_'+fp,None);persist_review_state_now()",
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
    x['ok']=True;x['src']='manual';st.session_state[hold_key][rid]=time.time();st.session_state.pop('prepared_excel_'+fp,None);persist_review_state_now()

def undo_ok(rid):
    x=st.session_state[sk][rid]
    if x.get('src')=='auto':return
    x['ok']=False;x['src']=None;st.session_state[hold_key].pop(rid,None);st.session_state.pop('prepared_excel_'+fp,None);persist_review_state_now()
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

    # Reconcile client 3371 with the supplied Chess June-August bultos export.
    # The historical lookup only covered clients present in the original census.
    sales_patch = [{'client': '3371', 'product': '1890 + BAJO CERO / 1 litro', 'jun': 4.0, 'jul': 8.0, 'aug': 5.0, 'monthlyBultos': 5.666666666666667, 'weeklyPacks': 1.2934782608695652, 'coverage': 'Con ventas registradas'}, {'client': '3371', 'product': '1890 + BAJO CERO / 473cc', 'jun': 0.0, 'jul': 2.0, 'aug': 1.0, 'monthlyBultos': 1.0, 'weeklyPacks': 0.22826086956521738, 'coverage': 'Con ventas registradas'}, {'client': '3371', 'product': '1890 + BAJO CERO / 710cc', 'jun': 0.0, 'jul': 0.0, 'aug': 0.25, 'monthlyBultos': 0.08333333333333333, 'weeklyPacks': 0.019021739130434784, 'coverage': 'Con ventas registradas'}]
    lookup_return = "    return c.set_index('client',drop=False),s.set_index(['client','product'],drop=False)"
    lookup_fixed = "    patches=pd.DataFrame(" + repr(sales_patch) + ")\n"
    lookup_fixed += "    s=pd.concat([s,patches],ignore_index=True).drop_duplicates(['client','product'],keep='last')\n"
    lookup_fixed += lookup_return
    src = _replace_once(src,lookup_return,lookup_fixed,'ventas verificadas cliente 3371')
    # Refresh automatic decisions for the reconciled rows; preserve manual work.
    refresh_state = "state=st.session_state[sk]\n"
    refresh_state += "if not st.session_state.get('sales3371_refreshed_'+fp):\n    st.session_state.pop('prepared_excel_'+fp,None)\n    st.session_state['sales3371_refreshed_'+fp]=True\n"
    refresh_state += "for r in d[d['client'].eq('3371') & d['product'].str.startswith('1890 + BAJO CERO / ')].itertuples():\n"
    refresh_state += "    x=state[r.id]\n"
    refresh_state += "    if x.get('src')!='manual' and x.get('corr') is None:\n"
    refresh_state += "        x['ok']=auto(r);x['src']='auto' if x['ok'] else None\n"
    src = _replace_once(src,'state=st.session_state[sk]',refresh_state,'recalcular OK cliente 3371')

    return src


try:
    _src = _optimized_source()
    exec(compile(_src, 'ddv_censo_v2', 'exec'), globals(), globals())
except Exception as exc:
    st.error(f'No pude iniciar la aplicación: {type(exc).__name__}: {exc}')
    with st.expander('Detalle técnico'):
        st.code(traceback.format_exc())
    st.stop()
