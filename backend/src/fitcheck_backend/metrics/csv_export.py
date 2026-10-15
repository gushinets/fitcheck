"""Stable identity-free CSV corresponding exactly to the JSON metric rows."""
import csv
import json

COLUMNS = ('start', 'end', 'timezone', 'environment', 'population', 'metric', 'dimensions',
           'value', 'numerator', 'denominator', 'sample_count', 'coverage', 'available', 'reason', 'data_start')


def safe_cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'"+value
    return value


def write_csv(report, stream):
    payload = report.to_json()
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator='\n')
    writer.writeheader()
    for row in payload['rows']:
        writer.writerow({key: safe_cell(value) for key, value in (payload['period'] | row).items()})
