from __future__ import annotations
import base64,gzip,hashlib,io,math,re,tempfile,time,unicodedata
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; DIST='DISTRIBUIDORA DEL VALLE S.A.'
DEFAULT_DRIVE_URL='https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot'
UNDO_SECONDS=8
st.set_page_config(page_title='Revisión Censo DDV',page_icon='✅',layout='wide')
st.markdown('''<style>:root{color-scheme:light!important}.stApp,[data-testid="stAppViewContainer"],[data-testid="stSidebar"]{background:#f6f8fb!important;color:#172033!important}[data-testid="stSidebar"]{border-right:1px solid #e5e9f0}.block-container{max-width:1750px;padding-top:1.2rem}.card{background:#fff;border:1px solid #e3e8ef;border-radius:10px;padding:.35rem .5rem;margin:.25rem 0}.auto{border-left:4px solid #16a34a}.corr{border-left:4px solid #2563eb}.pend{border-left:4px solid #cbd5e1}.muted{color:#64748b;font-size:.75rem}.num{font-weight:700;font-variant-numeric:tabular-nums}.ok{color:#15803d;font-weight:700}.blue{color:#1d4ed8;font-weight:700}.stButton button[kind="primary"]{background:#16a34a!important;border-color:#16a34a!important;color:#fff!important;font-weight:800!important}.stButton button[kind="primary"]:hover{background:#15803d!important;border-color:#15803d!important}.undo-note{background:#ecfdf3;border:1px solid #86efac;color:#166534;border-radius:8px;padding:.35rem .55rem;font-size:.78rem;font-weight:700}</style>''',unsafe_allow_html=True)

def txt(v):
    return '' if v is None or (isinstance(v,float) and math.isnan(v)) else str(v).strip()
def num(v):
    if v is None or pd.isna(v): return None
    if isinstance(v,(int,float)) and not isinstance(v,bool): return float(v)
    s=str(v).strip().replace(' ','')
    if not s:return None
    if ',' in s and '.' in s:s=s.replace('.','').replace(',','.') if s.rfind(',')>s.rfind('.') else s.replace(',','')
    else:s=s.replace(',','.')
    try:return float(s)
    except:return None
def fnum(v,d=2):
    if v is None or pd.isna(v):return '—'
    return f'{float(v):,.{d}f}'.replace(',','X').replace('.',',').replace('X','.')
def client_code(v):
    s=re.sub(r'\D','',re.sub(r'\.0$','',txt(v)));s=s[6:] if s.startswith('070549') else s
    return str(int(s)) if s else ''

def flags(v):
    s=txt(v).upper();o=set()
    if 'BAJO CERO' in s:o.add('BAJO CERO')
    if re.search(r'\b1890\b',s):o.add('1890')
    for x in ('BRAHMA','BUDWEISER'):
        if x in s:o.add(x)
    if 'QUILMES CLASICA' in s or 'QUILMES CLÁSICA' in s:o.add('QUILMES CLASICA')
    elif 'QUILMES' in s and 'BAJO CERO' not in s and '1890' not in s:o.add('QUILMES CLASICA')
    return o

def qmeta(q):
    u=q.upper().replace('CLÁSICA','CLASICA')
    if 'VENDE POR SEMANA' not in u:return None
    if '1890 + BAJO CERO' in u:g,t='1890 + BAJO CERO',{'1890','BAJO CERO'}
    elif 'QUILMES + BRAHMA' in u:g,t='QUILMES + BRAHMA',{'QUILMES CLASICA','BRAHMA'}
    elif 'QUILMES CLASICA' in u:g,t='QUILMES CLASICA',{'QUILMES CLASICA'}
    elif 'BRAHMA' in u:g,t='BRAHMA',{'BRAHMA'}
    elif 'BUDWEISER' in u:g,t='BUDWEISER',{'BUDWEISER'}
    else:return None
    if '1200CC' in u:p,unit='1200cc','cajones'
    elif '1 LITRO OW' in u:p,unit='1 litro OW','cajones'
    elif '1 LITRO' in u:p,unit='1 litro','cajones x12'
    elif '473CC' in u or '473 CC' in u:p,unit='473cc','packs x24'
    elif '710CC' in u or '710 CC' in u:p,unit='710cc','packs x16'
    else:return None
    return g,t,p,unit,f'{g} / {p}'

def read_parts(prefix):
    raw=''.join(p.read_text().strip() for p in sorted(DATA.glob(prefix+'*')))
    return io.BytesIO(gzip.decompress(base64.b64decode(raw)))
@st.cache_data(show_spinner=False)
def lookups():
    c=pd.read_csv(read_parts('client_lookup.b64.'),dtype={'client':str}).set_index('client',drop=False)
    s=pd.read_csv(read_parts('sales_lookup.b64.'),dtype={'client':str}).set_index(['client','product'],drop=False)
    return c,s

def normalized_filename(value):
    s=unicodedata.normalize('NFKD',txt(value)).encode('ascii','ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+',' ',s).strip()

def response_file_name(name):
    n=normalized_filename(Path(name).stem);ext=Path(name).suffix.lower()
    if ext not in {'.xlsx','.xlsm','.xls','.csv'} or 'RESPUESTAS' not in n:return False
    return 'DISTRIB' in n or re.search(r'(^| )ON( |$)',n) is not None

@st.cache_data(show_spinner=False,ttl=300)
def drive_response_files(drive_url,refresh_token=0):
    import gdown
    with tempfile.TemporaryDirectory() as td:
        items=gdown.download_folder(url=drive_url,output=td,quiet=True,use_cookies=False,skip_download=True) or []
        groups={'distrib':[],'on':[]}
        for item in items:
            name=Path(str(item.path)).name
            if not response_file_name(name):continue
            n=normalized_filename(name);family='distrib' if 'DISTRIB' in n else 'on'
            dates=re.findall(r'20\d{6}',n);date_key=max(dates) if dates else ''
            groups[family].append((date_key,normalized_filename(name),name,item.id))
        candidates=[]
        for family in ('distrib','on'):
            if groups[family]:
                _,_,name,file_id=max(groups[family])
                candidates.append((name,file_id))
        out=[]
        for name,file_id in candidates:
            target=Path(td)/name
            got=gdown.download(id=file_id,output=str(target),quiet=True,use_cookies=False)
            if got and target.exists() and target.stat().st_size>0:out.append((name,target.read_bytes()))
        return out

def combine_censo_files(files):
    frames=[]
    for order,(name,b) in enumerate(files):
        d=read_censo(b,name);d['__source_file']=name;d['__source_order']=order;frames.append(d)
    if not frames:return pd.DataFrame()
    return pd.concat(frames,ignore_index=True,sort=False)

def read_censo(b,name):
    bio=io.BytesIO(b)
    if name.lower().endswith('.csv'):
        try:d=pd.read_csv(bio,sep=None,engine='python')
        except UnicodeDecodeError:bio.seek(0);d=pd.read_csv(bio,sep=None,engine='python',encoding='cp1252')
    else:
        x=pd.ExcelFile(bio);d=None
        for sh in x.sheet_names:
            z=pd.read_excel(x,sheet_name=sh,nrows=5)
            if {'account_id','Comentario_Revision'}.issubset({str(c).strip() for c in z.columns}):d=pd.read_excel(x,sheet_name=sh);break
        if d is None:raise ValueError('No encontré account_id y Comentario_Revision en el Excel.')
    d.columns=[str(c).strip() for c in d.columns];return d

def build(d):
    c,s=lookups();w=d.copy()
    if 'DISTRIBUIDOR' in w:w=w[w.DISTRIBUIDOR.astype(str).str.strip().eq(DIST)]
    w=w[w.Comentario_Revision.notna() & w.Comentario_Revision.astype(str).str.strip().ne('')]
    qs=[(i,col,qmeta(str(col))) for i,col in enumerate(w.columns) if qmeta(str(col))]
    out=[]
    for ix,r in w.iterrows():
        account=txt(r.get('account_id'));cli=client_code(account);fl=flags(r.get('Comentario_Revision'));task=txt(r.get('task_id')) or f'fila-{ix+2}-{account}'
        ci=c.loc[cli] if cli in c.index else None
        for j,col,m in qs:
            g,tr,p,unit,prod=m;match=fl&tr
            if not match:continue
            si=s.loc[(cli,prod)] if (cli,prod) in s.index else None
            if isinstance(si,pd.DataFrame):si=si.iloc[0]
            get=lambda k,default=None: default if si is None or pd.isna(si.get(k,default)) else si.get(k,default)
            out.append(dict(id=f'{task}:{j+1}',client=cli,account=account,name=txt(ci['name']) if ci is not None else 'Nombre no disponible',promotor=txt(ci['promotor']) if ci is not None else 'Sin promotor asignado',supervisor=txt(ci['supervisor']) if ci is not None else 'Sin supervisor asignado',brand=g,product=prod,unit=unit,census=num(r.get(col)),weekly=num(get('weeklyPacks')),monthly=num(get('monthlyBultos')),jun=num(get('jun')),jul=num(get('jul')),aug=num(get('aug')),coverage=txt(get('coverage','Sin cruce')),comment=txt(r.get('Comentario_Revision')),field=str(col),task=task,date=txt(r.get('FECHA_TAREA'))[:10],source_file=txt(r.get('__source_file')),source_order=int(r.get('__source_order',0) or 0)))
    z=pd.DataFrame(out)
    if z.empty:return z
    z['_date']=pd.to_datetime(z['date'],errors='coerce')
    z=z.sort_values(['_date','source_order'],na_position='first').drop_duplicates(['client','field'],keep='last').drop(columns=['_date'])
    return z.sort_values(['client','product']).reset_index(drop=True)
def auto(r):return pd.notna(r.census) and pd.notna(r.weekly) and abs(float(r.census)-.25)<1e-9 and float(r.weekly)<.25
def fresh(d):return {r.id:{'ok':auto(r),'src':'auto' if auto(r) else None,'corr':None} for r in d.itertuples()}
def status(x):return 'OK automático' if x['ok'] and x['src']=='auto' else 'OK manual' if x['ok'] else 'Corregido' if x['corr'] is not None else 'Pendiente'
def enriched(d,state):
    z=d.copy();z['OK']=z.id.map(lambda x:state[x]['ok']);z['Corrección']=z.id.map(lambda x:state[x]['corr']);z['Estado']=z.id.map(lambda x:status(state[x]));z['Valor final']=z.apply(lambda r:r.census if state[r.id]['ok'] else state[r.id]['corr'],axis=1);return z

def export(z):
    cols=['client','account','name','promotor','supervisor','product','census','weekly','monthly','jun','jul','aug','OK','Corrección','Estado','Valor final','coverage','comment','task','date','source_file','field']
    names=['Código cliente','Account ID','Nombre','Promotor','Supervisor','Producto','Censado semanal','Venta prom. semanal','Venta prom. mensual','Junio','Julio','Agosto','OK','Corrección','Estado','Valor final','Cruce ventas','Comentario','Task ID','Fecha','Archivo origen','Pregunta original']
    return z[cols].rename(columns=dict(zip(cols,names)))

def excel(done,pend):
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='xlsxwriter') as w:
        for sh,df in [('Correcciones',export(done)),('Pendientes',export(pend))]:
            df.to_excel(w,sheet_name=sh,index=False);ws=w.sheets[sh];ws.freeze_panes(1,0);ws.autofilter(0,0,max(len(df),1),len(df.columns)-1);ws.set_column(0,len(df.columns)-1,16)
    return b.getvalue()

st.title('Revisión de Censo · DDV');st.caption('Drive → cruce de ventas → revisión por promotor → descarga de correcciones')
st.sidebar.subheader('Fuente de respuestas')
drive_url=st.sidebar.text_input('Carpeta de Google Drive',value=DEFAULT_DRIVE_URL)
if 'drive_refresh' not in st.session_state:st.session_state.drive_refresh=0
if st.sidebar.button('↻ Actualizar desde Drive',use_container_width=True):
    st.session_state.drive_refresh+=1;drive_response_files.clear();st.rerun()
st.sidebar.caption('Busca automáticamente los archivos Respuestas_DISTRIBU… y Respuestas_ON_2026…')
st.sidebar.caption('OK automático: solo Censado = 0,25 y Venta prom./sem. < 0,25.')
files=[];drive_error=''
try:files=drive_response_files(drive_url,st.session_state.drive_refresh) if drive_url.strip() else []
except Exception as e:drive_error=str(e)
if files:
    st.sidebar.success(f'{len(files)} archivo(s) de respuestas cargados desde Drive')
    for name,_ in files:st.sidebar.caption('• '+name)
else:
    if drive_error:st.sidebar.warning('No pude leer Drive automáticamente. Podés usar la carga manual de respaldo.')
    ups=st.sidebar.file_uploader('Respaldo: cargar respuestas manualmente',type=['xlsx','xlsm','xls','csv'],accept_multiple_files=True)
    files=[(u.name,u.getvalue()) for u in (ups or [])]
if not files:st.info('No encontré los archivos de respuestas en Drive. Revisá que la carpeta sea accesible por enlace o usá la carga manual.');st.stop()
try:d=build(combine_censo_files(files))
except Exception as e:st.error(f'No pude procesar las respuestas: {e}');st.stop()
if d.empty:st.warning('No encontré campos de revisión para DDV.');st.stop()
h=hashlib.sha256()
for name,b in files:h.update(name.encode('utf-8'));h.update(b)
fp=h.hexdigest()[:12];sk='state_'+fp

if sk not in st.session_state:st.session_state[sk]=fresh(d)
state=st.session_state[sk]
hold_key='ok_hold_'+fp
if hold_key not in st.session_state:st.session_state[hold_key]={}
holds=st.session_state[hold_key]
now=time.time()
for rid,ts in list(holds.items()):
    if now-ts>UNDO_SECONDS:holds.pop(rid,None)
if st.sidebar.button('↺ Reiniciar OK y correcciones',use_container_width=True):
    st.session_state[sk]=fresh(d);st.session_state[hold_key]={}
    for k in list(st.session_state):
        if k.startswith('w_'+fp):del st.session_state[k]
    st.rerun()
z=enriched(d,state);done=z[z.Estado!='Pendiente'];pend=z[z.Estado=='Pendiente']
a,b,c,d1=st.columns(4);a.metric('Campos',len(z));b.metric('OK',int(z.OK.sum()));c.metric('Corregidos',int(z['Corrección'].notna().sum()));d1.metric('Pendientes',len(pend))

f1,f2,f3,f4,f5,f6=st.columns(6)
sup=f1.selectbox('Supervisor',['Todos']+sorted(z.supervisor.unique()));pro=f2.selectbox('Promotor',['Todos']+sorted(z.promotor.unique()));bra=f3.selectbox('Marca',['Todas']+sorted(z.brand.unique()));prd=f4.selectbox('Producto',['Todos']+sorted(z[z.brand.eq(bra)].product.unique() if bra!='Todas' else z.product.unique()));est=f5.selectbox('Estado',['Todos','Pendientes','Completados']);okf=f6.selectbox('OK',['Todos','OK','No OK'])
search=st.text_input('Cliente',placeholder='Código, nombre o account ID')
f=z
if sup!='Todos':f=f[f.supervisor.eq(sup)]
if pro!='Todos':f=f[f.promotor.eq(pro)]
if bra!='Todas':f=f[f.brand.eq(bra)]
if prd!='Todos':f=f[f.product.eq(prd)]
if est=='Pendientes':f=f[f.Estado.eq('Pendiente')]
elif est=='Completados':f=f[~f.Estado.eq('Pendiente')]
if okf=='OK':f=f[f.OK]
elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]
if search.strip():
    q=search.lower();f=f[f.client.astype(str).str.lower().str.contains(q,regex=False)|f.name.str.lower().str.contains(q,regex=False)|f.account.astype(str).str.lower().str.contains(q,regex=False)]

x1,x2=st.columns(2);x1.download_button('⬇ Descargar corrección CSV',export(done).to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'correccion_censo_ddv.csv','text/csv',use_container_width=True);x2.download_button('⬇ Descargar corrección Excel',excel(done,pend),'correccion_censo_ddv.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
size=st.selectbox('Filas por página',[25,50,100],index=1);pages=max(1,math.ceil(len(f)/size));page=st.number_input('Página',1,pages,1);page_df=f.iloc[(page-1)*size:page*size];st.caption(f'Mostrando {len(f)} de {len(z)}')

def cb_corr(rid,key):
    x=st.session_state[sk][rid];v=txt(st.session_state[key]);n=num(v)
    if not v:x['corr']=None;return
    if n is None or n<0 or x['ok']:st.session_state[key]='' if x['corr'] is None else str(x['corr']).replace('.',',');return
    x['corr']=n;x['src']='manual'

def mark_ok(rid):
    x=state[rid]
    if x['corr'] is not None:return
    x['ok']=True;x['src']='manual';holds[rid]=time.time();st.rerun()

def undo_ok(rid):
    x=state[rid]
    if x.get('src')=='auto':return
    x['ok']=False;x['src']=None;holds.pop(rid,None);st.rerun()

for r in page_df.itertuples():
    x=state[r.id];css='auto' if x['ok'] else 'corr' if x['corr'] is not None else 'pend'
    st.markdown(f'<div class="card {css}">',unsafe_allow_html=True);co=st.columns([.7,1.5,1.5,2.2,.7,.8,.5,1,1])
    co[0].markdown(f'**{r.client}**<div class="muted">{r.account}</div>',unsafe_allow_html=True);co[1].markdown(f'{r.name}<div class="muted">{r.supervisor}</div>',unsafe_allow_html=True);co[2].write(r.promotor);co[3].markdown(f'**{r.product}**<div class="muted">{r.unit}</div>',unsafe_allow_html=True);co[4].markdown(f'<span class="num">{fnum(r.census)}</span>',unsafe_allow_html=True);co[5].markdown(f'<span class="num">{fnum(r.weekly)}</span>',unsafe_allow_html=True)
    kc=f'w_{fp}_c_{r.id}'
    held=r.id in holds and time.time()-holds[r.id]<=UNDO_SECONDS
    if x['ok'] and x.get('src')=='manual' and held:
        if co[6].button('✅ OK',key=f'ok_{fp}_{r.id}',type='primary',use_container_width=True):undo_ok(r.id)
        co[8].markdown('<div class="undo-note">OK marcado · tocá de nuevo para deshacer</div>',unsafe_allow_html=True)
    elif x['ok']:
        co[6].button('✅ OK',key=f'ok_{fp}_{r.id}',type='primary',disabled=True,use_container_width=True)
    else:
        if co[6].button('OK',key=f'ok_{fp}_{r.id}',disabled=x['corr'] is not None,use_container_width=True):mark_ok(r.id)
    if kc not in st.session_state:st.session_state[kc]='' if x['corr'] is None else str(x['corr']).replace('.',',')
    co[7].text_input('Corrección',key=kc,disabled=x['ok'],placeholder='Bloqueado por OK' if x['ok'] else 'Completar',label_visibility='collapsed',on_change=cb_corr,args=(r.id,kc))
    s=status(x)
    if not (x['ok'] and x.get('src')=='manual' and held):co[8].markdown(f'<span class="{"ok" if s.startswith("OK") else "blue" if s=="Corregido" else "muted"}">{s}</span>',unsafe_allow_html=True)
    with st.expander('Detalle'):st.write(f'**Archivo origen:** {r.source_file}');st.write(f'**Comentario:** {r.comment}');st.write(f'**Pregunta:** {r.field}');st.write(f'**Ventas:** Jun {fnum(r.jun,3)} · Jul {fnum(r.jul,3)} · Ago {fnum(r.aug,3)} · Prom. mes {fnum(r.monthly,3)}')
    st.markdown('</div>',unsafe_allow_html=True)
st.caption('Todo caso distinto de Censado 0,25 + Venta semanal menor a 0,25 queda para revisión manual.')
