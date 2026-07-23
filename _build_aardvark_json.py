"""Build spec-compliant Aardvark JSON records directly from
aardvark_resources.csv + aardvark_distributions.csv, bypassing the
OpenGeoMetadata Studio's CSV import/export (which currently drops
distribution labels and does not reliably emit downloadUrl as the
required array-of-objects). Overwrites aardvark_json/.
"""
import csv
import json
import os
import re
from collections import defaultdict

RESOURCES_IN = 'aardvark_resources.csv'
DISTRIBUTIONS_IN = 'aardvark_distributions.csv'
OUT_DIR = 'aardvark_json'

SCALAR_MAP = {
    'Title': 'dct_title_s',
    'Bounding Box': 'dcat_bbox',
    'Date Issued': 'dct_issued_s',
    'File Size': 'gbl_fileSize_s',
    'Format': 'dct_format_s',
    'Geometry': 'locn_geometry',
    'ID': 'id',
    'Metadata Version': 'gbl_mdVersion_s',
    'Modified': 'gbl_mdModified_dt',
    'Provider': 'schema_provider_s',
    'Access Rights': 'dct_accessRights_s',
    'WxS Identifier': 'gbl_wxsIdentifier_s',
}

ARRAY_MAP = {
    'Creator': 'dct_creator_sm',
    'Date Range': 'gbl_dateRange_drsim',
    'Description': 'dct_description_sm',
    'Keyword': 'dcat_keyword_sm',
    'Language': 'dct_language_sm',
    'Publisher': 'dct_publisher_sm',
    'Resource Class': 'gbl_resourceClass_sm',
    'Resource Type': 'gbl_resourceType_sm',
    'Rights': 'dct_rights_sm',
    'Rights Holder': 'dct_rightsHolder_sm',
    'Spatial Coverage': 'dct_spatial_sm',
    'Subject': 'dct_subject_sm',
    'Theme': 'dcat_theme_sm',
}

BOOL_MAP = {
    'Georeferenced': 'gbl_georeferenced_b',
    'Suppressed': 'gbl_suppressed_b',
}

REFERENCE_URI = {
    'download': 'http://schema.org/downloadUrl',
    'url': 'http://schema.org/url',
    'wfs': 'http://www.opengis.net/def/serviceType/ogc/wfs',
    'wms': 'http://www.opengis.net/def/serviceType/ogc/wms',
}

# Always-present multivalue fields with no current data source; emit as empty arrays
# for schema completeness (mirrors the Studio's own Resource model).
EMPTY_ARRAY_FIELDS = [
    'dct_alternative_sm', 'gbl_displayNote_sm', 'dct_identifier_sm', 'dct_license_sm',
    'pcdm_memberOf_sm', 'dct_isPartOf_sm', 'dct_source_sm', 'dct_isVersionOf_sm',
    'dct_replaces_sm', 'dct_isReplacedBy_sm', 'dct_relation_sm', 'dct_temporal_sm',
]


def to_bool(v):
    return v.strip().lower() == 'true'


def pipe_list(v):
    return [x for x in v.split('|') if x] if v else []


# --- load distributions, grouped by ID ---
dist_by_id = defaultdict(list)
with open(DISTRIBUTIONS_IN, encoding='utf-8') as f:
    for row in csv.DictReader(f):
        dist_by_id[row['ID']].append(row)

os.makedirs(OUT_DIR, exist_ok=True)
existing = set(os.listdir(OUT_DIR))

written = 0
issues = []

with open(RESOURCES_IN, encoding='utf-8') as f:
    for row in csv.DictReader(f):
        rid = row['ID']
        rec = {}

        for label, field in SCALAR_MAP.items():
            val = row.get(label, '').strip()
            if val:
                rec[field] = val

        for label, field in ARRAY_MAP.items():
            rec[field] = pipe_list(row.get(label, ''))

        for label, field in BOOL_MAP.items():
            rec[field] = to_bool(row.get(label, ''))

        # Index Year: array of integers. Fall back to the first plausible 4-digit
        # year found in messy pre-existing text (date ranges, full dates, etc.)
        # rather than leaving the facet blank.
        iy_raw = pipe_list(row.get('Index Year', ''))
        years = []
        for y in iy_raw:
            try:
                years.append(int(y))
            except ValueError:
                m = re.search(r'(1[5-9]\d{2}|20\d{2})', y)
                if m:
                    years.append(int(m.group(1)))
                    issues.append((rid, f'extracted year {m.group(1)} from messy value {y!r}'))
                else:
                    issues.append((rid, f'no plausible year found in {y!r}'))
        rec['gbl_indexYear_im'] = sorted(set(years))

        for field in EMPTY_ARRAY_FIELDS:
            rec[field] = []

        # --- references ---
        refs = {}
        for d in dist_by_id.get(rid, []):
            uri = REFERENCE_URI.get(d['Type'])
            if not uri:
                issues.append((rid, f'unknown distribution type {d["Type"]!r}'))
                continue
            if d['Type'] == 'download':
                refs.setdefault(uri, []).append({'url': d['URL'], 'label': d['Label'] or None})
            else:
                if uri in refs:
                    issues.append((rid, f'duplicate non-download reference {d["Type"]!r}'))
                refs[uri] = d['URL']
        if 'http://schema.org/downloadUrl' not in refs:
            issues.append((rid, 'no download reference'))
        rec['dct_references_s'] = json.dumps(refs, ensure_ascii=False)

        out_path = os.path.join(OUT_DIR, f'{rid}.json')
        with open(out_path, 'w', encoding='utf-8') as jf:
            json.dump(rec, jf, indent=2, ensure_ascii=False)
        written += 1
        existing.discard(f'{rid}.json')

print('records written:', written)
print('issues:', len(issues))
for i in issues[:30]:
    print(' ', i)
print('stale files left over in aardvark_json (not regenerated this run):', len(existing))
for e in sorted(existing)[:20]:
    print(' ', e)
