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
# Auditoría de ventas — 01/10/2026

La comparación usa **compras al distribuidor de junio–agosto 2026**, en bultos,
del archivo `trimestre bultos.txt`. No es un trimestre móvil ni una medición de
venta del comercio. Mensual = suma de los tres meses / 3; semanal = suma × 7 / 92.

`data/sales_jun_aug_2026.csv.gz` contiene todos los pares con movimientos del
archivo completo, sin filtrar por los clientes presentes en un censo anterior.
`sales_snapshot.py` completa ceros sólo para clientes identificados en el archivo
y presentaciones validadas. Clientes desconocidos, OW y 1200 cc quedan N/D.
Los ajustes negativos se conservan. Por criterio solicitado, N/D recibe OK automático; mantiene el dato de venta N/D. Para valores numéricos se conserva diferencia absoluta ≤ 0,50; cantidades negativas no se aprueban automáticamente.

El manifiesto documenta fuente, huellas, períodos, clientes y equivalencias de los
16 SKUs. El cargador verifica integridad, duplicados y fórmulas. La posición de
preguntas se controla para proteger los identificadores heredados de correcciones.
Las decisiones manuales tienen prioridad al restaurar y se guardan como cambios
individuales, preservando registros de otros censos. La escritura simultánea del
mismo archivo de Drive no cuenta con control transaccional; evitar ediciones
simultáneas hasta migrar el almacenamiento o incorporar control de concurrencia.

Reproducir la referencia desde el archivo fuente:

```powershell
python sales_snapshot.py "C:/ruta/trimestre bultos.txt"
$env:CENSO_SALES_SOURCE="C:/ruta/trimestre bultos.txt"
python -m unittest discover -v
```

Sin `CENSO_SALES_SOURCE`, se ejecutan las pruebas del snapshot publicado y se
omite únicamente la reconciliación opcional contra el archivo privado completo.
