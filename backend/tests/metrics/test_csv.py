import csv
import io
from fitcheck_backend.metrics.report_types import MetricReport, MetricRow
from fitcheck_backend.metrics.csv_export import write_csv
from .test_calculations import options


def test_csv_formula_escaping_and_no_subject_ids():
    report=MetricReport(options=options(),rows=[MetricRow(metric='=SUM(1)',dimensions={'campaign':'@bad'},value=None,available=False,reason='-missing source')])
    stream=io.StringIO()
    write_csv(report,stream)
    cells=list(csv.DictReader(io.StringIO(stream.getvalue())))
    assert cells[0]['metric']=="'=SUM(1)"
    assert cells[0]['reason']=="'-missing source"
    assert cells[0]['value']==''
    assert cells[0]['environment']=='test'
    assert 'subject_id' not in stream.getvalue()
    assert len(report.to_json()['rows'])==len(cells)
