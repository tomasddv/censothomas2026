# Revisión de Censo DDV

App Streamlit para revisar el censo de Distribuidora del Valle.

## Funciones
- Carga XLSX/XLSM/XLS/CSV de respuestas del censo.
- Detecta `account_id` y `Comentario_Revision`.
- Cruza nombre de cliente, promotor, supervisor y venta promedio de junio-julio-agosto.
- OK automático únicamente cuando **Censado = 0,25** y **Venta promedio semanal < 0,25**.
- Todo el resto queda para revisión manual.
- OK y Corrección son mutuamente excluyentes.
- Filtros por supervisor, promotor, marca, producto, estado y OK/No OK.
- Botón para reiniciar OK/correcciones al estado inicial.
- Descarga de correcciones en CSV y Excel.
- Tema claro.

## Streamlit Community Cloud
Repositorio: `tomasddv/planificacion`

Main file path:
`censo_revision/app.py`

## Dependencias
Streamlit instalará las dependencias desde `censo_revision/requirements.txt` si el despliegue las contempla desde esa carpeta. Si tu despliegue busca únicamente `requirements.txt` en la raíz del repo, copiá también este archivo a la raíz o agregá allí estas dependencias.
