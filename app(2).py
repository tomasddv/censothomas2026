from __future__ import annotations

import textwrap
import urllib.request

import streamlit as st

# El código funcional completo queda fijado en este commit inmutable. Este bootstrap
# aplica optimizaciones de rendimiento antes de ejecutarlo, sin tocar los datos
# auxiliares embebidos ni la lógica de negocio ya validada.
BASE_APP_URL = (
    "https://raw.githubusercontent.com/tomasddv/censothomas2026/"
    "0d5d763c47d89dbd2e414fb3d659d1a6aeafffa0/app.py"
)


@st.cache_data(show_spinner=False, ttl=86400)
def _load_base_app() -> str:
    req = urllib.request.Request(BASE_APP_URL, headers={"User-Agent": "DDV-Censo/fast-ui"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8")


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"No pude aplicar la optimización: {label}")
    return source.replace(old, new, 1)


def _optimized_source() -> str:
    src = _load_base_app()

    # 1) No volver a leer/parsear los Excel ni reconstruir el cruce en cada rerun.
    src = _replace_once(
        src,
        "def combine_censo_files(files):",
        "@st.cache_data(show_spinner=False)\ndef combine_censo_files(files):",
        "cache de combinación",
    )
    src = _replace_once(
        src,
        "def read_censo(b,name):",
        "@st.cache_data(show_spinner=False)\ndef read_censo(b,name):",
        "cache de lectura",
    )
    src = _replace_once(
        src,
        "def build(d):",
        "@st.cache_data(show_spinner=False)\ndef build(d):",
        "cache de cruce",
    )

    # 2) Enriquecimiento vectorizado: evita DataFrame.apply fila por fila.
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
    src = _replace_once(src, old_enriched, new_enriched, "enriquecimiento rápido")

    # 3) Excel bajo demanda: no regenerarlo cada vez que se marca OK o se escribe un valor.
    old_downloads = """x1,x2=st.columns(2);x1.download_button('⬇ Descargar corrección CSV',export(done).to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'correccion_censo_ddv.csv','text/csv',use_container_width=True);x2.download_button('⬇ Descargar corrección Excel',excel(done,pend),'correccion_censo_ddv.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
"""
    new_downloads = """x1,x2=st.columns(2)
x1.download_button('⬇ Descargar corrección CSV',export(done).to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'correccion_censo_ddv.csv','text/csv',use_container_width=True)
_excel_key='prepared_excel_'+fp
if x2.button('Preparar Excel actualizado',key='prep_excel_'+fp,use_container_width=True):
    with st.spinner('Preparando Excel…'):
        st.session_state[_excel_key]=excel(done,pend)
if _excel_key in st.session_state:
    x2.download_button('⬇ Descargar corrección Excel',st.session_state[_excel_key],'correccion_censo_ddv.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True,key='download_excel_'+fp)
"""
    src = _replace_once(src, old_downloads, new_downloads, "Excel bajo demanda")

    # Invalidar el Excel preparado cuando cambia una corrección o un OK.
    src = _replace_once(
        src,
        "if not v:x['corr']=None;return",
        "if not v:x['corr']=None;st.session_state.pop('prepared_excel_'+fp,None);return",
        "invalidación al borrar corrección",
    )
    src = _replace_once(
        src,
        "x['corr']=n;x['src']='manual'",
        "x['corr']=n;x['src']='manual';st.session_state.pop('prepared_excel_'+fp,None)",
        "invalidación al corregir",
    )
    src = _replace_once(
        src,
        "x['ok']=True;x['src']='manual';holds[rid]=time.time();st.rerun()",
        "x['ok']=True;x['src']='manual';holds[rid]=time.time();st.session_state.pop('prepared_excel_'+fp,None);st.rerun(scope='fragment')",
        "OK rápido",
    )
    src = _replace_once(
        src,
        "x['ok']=False;x['src']=None;holds.pop(rid,None);st.rerun()",
        "x['ok']=False;x['src']=None;holds.pop(rid,None);st.session_state.pop('prepared_excel_'+fp,None);st.rerun(scope='fragment')",
        "deshacer OK rápido",
    )
    src = _replace_once(
        src,
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={}\n    for k in list(st.session_state):",
        "st.session_state[sk]=fresh(d);st.session_state[hold_key]={};st.session_state.pop('prepared_excel_'+fp,None)\n    for k in list(st.session_state):",
        "invalidación al reiniciar",
    )

    # 4) Menos componentes por render inicial. Se puede subir a 50/100 cuando haga falta.
    src = _replace_once(
        src,
        "size=st.selectbox('Filas por página',[25,50,100],index=1)",
        "size=st.selectbox('Filas por página',[10,25,50,100],index=1)",
        "paginación rápida",
    )

    # 5) El filtro No OK sólo considera el período real de deshacer.
    src = _replace_once(
        src,
        "elif okf=='No OK':f=f[(~f.OK)|f.id.isin(set(holds))]",
        "elif okf=='No OK':\n    _active_holds={rid for rid,ts in holds.items() if time.time()-ts<=UNDO_SECONDS}\n    f=f[(~f.OK)|f.id.isin(_active_holds)]",
        "filtro No OK",
    )

    # 6) Aislar toda la grilla en un fragmento. Desde acá, OK, correcciones,
    # filtros y paginado ya no vuelven a ejecutar Drive + Excel + cruce completo.
    marker = "z=enriched(d,state);done=z[z.Estado!='Pendiente'];pend=z[z.Estado=='Pendiente']"
    pos = src.find(marker)
    if pos < 0:
        raise RuntimeError("No pude aplicar la optimización: fragmento de revisión")
    prefix, tail = src[:pos], src[pos:]
    src = prefix + "@st.fragment\ndef _review_fragment():\n" + textwrap.indent(tail, "    ") + "\n\n_review_fragment()\n"
    return src


try:
    _src = _optimized_source()
    exec(compile(_src, "ddv_censo_optimized", "exec"), globals(), globals())
except Exception as exc:
    st.error(f"No pude iniciar la versión optimizada: {type(exc).__name__}: {exc}")
    st.stop()
