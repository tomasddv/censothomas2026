"""Complete, reproducible June–August 2026 purchase reference in bultos."""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict, Counter
import csv
import gzip
import hashlib
import io
import json
import math
import pandas as pd

PERIODS = {'jun-26': 0, 'jul-26': 1, 'ago-26': 2}
BRANDS = {'QUILMES': 'QUILMES CLASICA', 'QUILMES CLASICA': 'QUILMES CLASICA',
          'BRAHMA': 'BRAHMA', 'BUDWEISER': 'BUDWEISER',
          'QUILMES 1890': '1890 + BAJO CERO', 'QUILMES BAJO CERO': '1890 + BAJO CERO'}
PACKS = {'473 CC LATAS': ('473cc', 'packs x24'),
         '710 CC LATAS': ('710cc', 'packs x16'),
         '1000 CC VIDRIO': ('1 litro', 'cajones x12')}
DATA = Path(__file__).resolve().parent / 'data'


def validate_census_schema(columns):
    """Legacy review IDs contain a column number; fail closed on column drift."""
    expected=json.loads((DATA/'census_schema.json').read_text(encoding='utf-8'))
    for i,col in enumerate(columns,1):
        if 'vende por semana' in col.lower() and expected.get(col)!=i:
            raise ValueError('Cambió la posición o el nombre de una pregunta del censo. Se detuvo la carga para no aplicar correcciones guardadas a otro producto.')


def compile_snapshot(source, output=DATA):
    """Read the ENTIRE export, never restrict sales to a census population."""
    raw = Path(source).read_bytes()
    reader = csv.reader(io.StringIO(raw.decode('cp1252')), delimiter='\t')
    header = next(reader)
    assert header[4] == 'Cod. Cliente' and header[40] == 'Cantidades Totales'
    values = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
    active, seen, skus = set(), set(), {}
    counts = Counter()
    excluded = Counter()
    for line, r in enumerate(reader, 2):
        if len(r) != len(header):
            raise ValueError(f'Fila {line}: estructura inválida')
        if tuple(r) in seen:
            raise ValueError(f'Fila {line}: duplicado exacto; revisar origen')
        seen.add(tuple(r))
        mi = PERIODS[r[2]]  # Fail rather than silently mix periods.
        counts[r[2]] += 1
        cli = str(int(r[4])); active.add(cli)
        amount = Decimal(r[40].replace('.', '').replace(',', '.'))
        if not amount.is_finite():
            raise ValueError(f'Fila {line}: cantidad inválida')
        brand = BRANDS.get(r[20])
        if not brand:
            continue
        if r[23] not in PACKS:
            excluded[(r[17], r[18], r[23])] += 1
            continue
        pack, unit = PACKS[r[23]]
        desc = r[18].upper()
        valid = (pack == '473cc' and ('4X6' in desc or 'X24' in desc)
                 or pack == '710cc' and '4X4' in desc
                 or pack == '1 litro' and 'X12' in desc and 'RET' in desc)
        if not valid:
            raise ValueError(f'Bulto sin equivalencia validada: SKU {r[17]} {desc}')
        product = brand + ' / ' + pack
        values[cli, product][mi] += amount
        skus[r[17]] = dict(sku=r[17], description=r[18], product=product, unit=unit)
    if set(counts) != set(PERIODS):
        raise ValueError('Falta al menos un mes completo')
    records = []
    for (cli, product), v in sorted(values.items()):
        records.append(dict(client=cli, product=product, jun=float(v[0]), jul=float(v[1]), aug=float(v[2]),
                            monthlyBultos=float(sum(v)/3), weeklyPacks=float(sum(v)*7/92),
                            coverage='Con movimientos en archivo'))
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    payload = pd.DataFrame(records).to_csv(index=False).encode('utf-8')
    (output/'sales_jun_aug_2026.csv.gz').write_bytes(gzip.compress(payload, mtime=0))
    meta = dict(source=Path(source).name, sha256=hashlib.sha256(raw).hexdigest(),
                start='2026-06-01', end='2026-08-31', days=92, months=3, unit='bultos',
                period_rows=dict(counts), rows=sum(counts.values()), clients=sorted(active, key=int),
                products=sorted({r['product'] for r in skus.values()}), skus=list(skus.values()),
                excluded=[dict(sku=k[0], description=k[1], caliber=k[2], rows=v) for k,v in excluded.items()],
                data_sha256=hashlib.sha256(payload).hexdigest())
    (output/'sales_manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    return meta


def load_sales_snapshot():
    meta = json.loads((DATA/'sales_manifest.json').read_text(encoding='utf-8'))
    payload = gzip.decompress((DATA/'sales_jun_aug_2026.csv.gz').read_bytes())
    if hashlib.sha256(payload).hexdigest() != meta['data_sha256']:
        raise ValueError('La referencia de ventas no coincide con su control de integridad')
    s = pd.read_csv(io.BytesIO(payload), dtype={'client':str})
    if s.duplicated(['client','product']).any():
        raise ValueError('Referencia de ventas duplicada')
    if meta['days'] != 92 or meta['months'] != 3 or meta['unit'] != 'bultos':
        raise ValueError('Período o unidad de ventas incorrecto')
    cols = ['jun','jul','aug','monthlyBultos','weeklyPacks']
    if not s[cols].map(math.isfinite).all().all():
        raise ValueError('Ventas con cantidades no finitas')
    totals = s[['jun','jul','aug']].sum(axis=1)
    if ((s.monthlyBultos-totals/3).abs()>1e-8).any() or ((s.weeklyPacks-totals*7/92).abs()>1e-8).any():
        raise ValueError('Promedios de ventas inconsistentes')
    index = pd.MultiIndex.from_product([meta['clients'],meta['products']],names=['client','product'])
    s = s.set_index(['client','product']).reindex(index)
    s[cols] = s[cols].fillna(0)
    s['coverage'] = s['coverage'].fillna('Sin movimientos de este producto en el archivo')
    return s.reset_index()


if __name__ == '__main__':
    import sys
    m = compile_snapshot(sys.argv[1])
    print(json.dumps({k:m[k] for k in ['source','rows','period_rows','sha256']},ensure_ascii=False))
