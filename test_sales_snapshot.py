"""Snapshot invariants plus optional independent reconciliation to the private TSV.

Run: python -m unittest test_sales_snapshot
Set CENSO_SALES_SOURCE to the original trimestre bultos.txt for the full-source test.
"""
import csv
import gzip
import json
import os
import shutil
import tempfile
import unittest
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import sales_snapshot


class SalesSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sales = sales_snapshot.load_sales_snapshot().set_index(['client', 'product'])

    def test_complete_coverage_and_totals(self):
        self.assertTrue(self.sales.index.is_unique)
        self.assertEqual(len(self.sales), 1486 * 12)
        expected = [22249.4167, 23690.9165, 32030.2709]
        for column, total in zip(['jun', 'jul', 'aug'], expected):
            self.assertAlmostEqual(self.sales[column].sum(), total, places=6)
        totals = self.sales[['jun', 'jul', 'aug']].sum(axis=1)
        self.assertLess((self.sales.monthlyBultos - totals / 3).abs().max(), 1e-8)
        self.assertLess((self.sales.weeklyPacks - totals * 7 / 92).abs().max(), 1e-8)

    def test_absence_is_distinct_from_zero(self):
        clients = self.sales.index.get_level_values('client')
        self.assertNotIn('5135', clients)
        self.assertNotIn('999999999', clients)
        self.assertNotIn(('3371', 'BRAHMA / 1 litro OW'), self.sales.index)
        zero = self.sales.loc[('5442', '1890 + BAJO CERO / 1 litro')]
        self.assertEqual(list(zero[['jun', 'jul', 'aug']]), [0, 0, 0])
        self.assertIn('Sin movimientos', zero.coverage)

    def test_reported_cases_and_other_products_for_same_clients(self):
        expected = {
            ('3371', '1890 + BAJO CERO / 1 litro'): [4, 8, 5],
            ('5442', 'BRAHMA / 473cc'): [3, 1, 0],
            ('5442', 'BRAHMA / 710cc'): [2, 3, 4],
            ('3371', 'BUDWEISER / 710cc'): [3, 3, 6],
        }
        for key, values in expected.items():
            self.assertEqual(list(self.sales.loc[key, ['jun', 'jul', 'aug']]), values)

    def test_corrupt_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            shutil.copy(sales_snapshot.DATA / 'sales_manifest.json', folder)
            payload = gzip.decompress((sales_snapshot.DATA / 'sales_jun_aug_2026.csv.gz').read_bytes())
            (folder / 'sales_jun_aug_2026.csv.gz').write_bytes(gzip.compress(payload + b'\n'))
            with patch.object(sales_snapshot, 'DATA', folder):
                with self.assertRaisesRegex(ValueError, 'integridad'):
                    sales_snapshot.load_sales_snapshot()

    @unittest.skipUnless(os.environ.get('CENSO_SALES_SOURCE'), 'Set CENSO_SALES_SOURCE for private-source reconciliation')
    def test_every_pair_against_independent_source_aggregation(self):
        # Deliberately do not reuse production mappings/parser or compile_snapshot.
        brand_map = {'QUILMES': 'QUILMES CLASICA', 'QUILMES CLASICA': 'QUILMES CLASICA',
                     'BRAHMA': 'BRAHMA', 'BUDWEISER': 'BUDWEISER',
                     'QUILMES 1890': '1890 + BAJO CERO', 'QUILMES BAJO CERO': '1890 + BAJO CERO'}
        format_map = {'473 CC LATAS': '473cc', '710 CC LATAS': '710cc', '1000 CC VIDRIO': '1 litro'}
        values = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
        active = set()
        with open(os.environ['CENSO_SALES_SOURCE'], encoding='cp1252', newline='') as source:
            reader = csv.reader(source, delimiter='\t')
            header = next(reader)
            self.assertEqual(header[4], 'Cod. Cliente')
            self.assertEqual(header[40], 'Cantidades Totales')
            for cells in reader:
                client = str(int(cells[4]))
                active.add(client)
                brand = brand_map.get(cells[20]); pack = format_map.get(cells[23])
                if brand and pack:
                    month = ['jun-26', 'jul-26', 'ago-26'].index(cells[2])
                    values[client, brand + ' / ' + pack][month] += Decimal(cells[40].replace('.', '').replace(',', '.'))
        self.assertEqual(set(self.sales.index.get_level_values('client')), active)
        self.assertEqual(len(values), 5940)
        for key, record in self.sales.iterrows():
            expected = values.get(key, [Decimal(0)] * 3)
            for column, number in zip(['jun', 'jul', 'aug'], expected):
                self.assertAlmostEqual(record[column], float(number), places=8, msg=f'{key} {column}')
            self.assertAlmostEqual(record.monthlyBultos, float(sum(expected) / 3), places=8)
            self.assertAlmostEqual(record.weeklyPacks, float(sum(expected) * 7 / 92), places=8)
        self.assertTrue(set(values).issubset(self.sales.index))


if __name__ == '__main__':
    unittest.main()
