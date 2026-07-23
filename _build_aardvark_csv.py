"""Convert the FGDC XML collection to Aardvark Resources + Distributions CSVs
for OpenGeoMetadata Studio ingest, per fgdc_aardvark_crosswalk.csv.
"""
import csv
import glob
import re
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

RESOURCES_OUT = 'aardvark_resources.csv'
DISTRIBUTIONS_OUT = 'aardvark_distributions.csv'

GBL_BASE = 'https://geodata.library.columbia.edu/catalog/'
WFS_URL = 'https://geoserver.cul.columbia.edu/geoserver/sde/ows'
WMS_URL = 'https://geoserver.cul.columbia.edu/geoserver/wms/sde'

RESOURCE_COLUMNS = [
    'Title', 'Bounding Box', 'Creator', 'Date Issued', 'Date Range', 'Description',
    'File Size', 'Format', 'Geometry', 'Georeferenced', 'ID', 'Index Year',
    'Keyword', 'Language', 'Metadata Version', 'Modified', 'Provider', 'Publisher',
    'Resource Class', 'Resource Type', 'Rights', 'Rights Holder', 'Spatial Coverage',
    'Subject', 'Suppressed', 'Theme', 'Access Rights', 'WxS Identifier',
]

MODIFIED_TS = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

resource_rows = []
dist_rows = []
issues = []


def text(el):
    return ' '.join((el.text or '').split()) if el is not None else ''


def pipe(values):
    return '|'.join(v for v in values if v)


for fname in sorted(set(glob.glob('*.xml')) | set(glob.glob('*.XML'))):
    root = ET.parse(fname).getroot()
    idinfo = root.find('idinfo')
    citeinfo = root.find('idinfo/citation/citeinfo')
    distinfo = root.find('distinfo')

    # --- id ---
    resdesc_el = distinfo.find('resdesc') if distinfo is not None else None
    rid = text(resdesc_el)

    # --- Access Rights ---
    accconst_el = idinfo.find('accconst')
    accconst = text(accconst_el)
    access_rights = 'public' if accconst == 'None' else 'restricted'
    is_public = access_rights == 'public'

    # --- Bounding Box / Geometry ---
    bounding = idinfo.find('spdom/bounding')
    envelope = ''
    if bounding is not None:
        w = text(bounding.find('westbc'))
        e = text(bounding.find('eastbc'))
        n = text(bounding.find('northbc'))
        s = text(bounding.find('southbc'))
        if w and e and n and s:
            envelope = f'ENVELOPE({w}, {e}, {n}, {s})'
        else:
            issues.append((fname, 'incomplete bounding box'))

    # --- Creator ---
    creators = [text(o) for o in citeinfo.findall('origin')] if citeinfo is not None else []

    # --- Date Issued ---
    pubdate = text(citeinfo.find('pubdate')) if citeinfo is not None else ''

    # --- Date Range + Index Year ---
    rngdates = idinfo.find('timeperd/timeinfo/rngdates')
    caldate = idinfo.find('timeperd/timeinfo/sngdate/caldate')
    date_range = ''
    index_years = []
    if rngdates is not None:
        beg = text(rngdates.find('begdate'))
        end = text(rngdates.find('enddate'))
        if beg and end:
            date_range = f'[{beg} TO {end}]'
            try:
                b, e = int(beg), int(end)
                if b <= e:
                    index_years = [str(y) for y in range(b, e + 1)]
                else:
                    index_years = [beg, end]
            except ValueError:
                issues.append((fname, f'non-integer rngdates {beg}-{end}'))
    elif caldate is not None and text(caldate):
        index_years = [text(caldate)]
    if not index_years and pubdate:
        index_years = [pubdate]
    if not index_years:
        issues.append((fname, 'no index year derivable'))

    # --- Description ---
    abstract = text(idinfo.find('descript/abstract'))

    # --- File Size / Format ---
    filesize = text(distinfo.find('.//transize')) if distinfo is not None else ''
    formname = text(distinfo.find('.//formname')) if distinfo is not None else ''

    # --- Georeferenced ---
    georeferenced = 'true' if root.find('spref') is not None else 'false'

    # --- Keyword (uncontrolled) ---
    keywords = []
    for t in idinfo.findall('keywords/theme'):
        kt = text(t.find('themekt'))
        if kt == 'None':
            keywords += [text(k) for k in t.findall('themekey')]

    # --- Language ---
    languages = [text(l) for l in idinfo.findall('descript/langdata')]

    # --- Publisher ---
    publisher = text(citeinfo.find('pubinfo/publish')) if citeinfo is not None else ''

    # --- Resource Class ---
    title = text(citeinfo.find('title')) if citeinfo is not None else ''
    if fname.startswith('cul_scannedpublic_') or '(Scanned Map)' in title:
        resource_class = 'Maps'
    elif ('orthoimagery' in title.lower() or 'orthophoto' in title.lower()) and 'index' not in title.lower():
        resource_class = 'Imagery'
    else:
        resource_class = 'Datasets'

    # --- Resource Type ---
    direct = text(root.find('spdoinfo/direct'))
    sdtstype = text(root.find('spdoinfo/ptvctinf/sdtsterm/sdtstype'))
    if direct == 'Raster':
        resource_type = 'Raster data'
    elif sdtstype == 'String':
        resource_type = 'Line data'
    elif sdtstype == 'G-polygon':
        resource_type = 'Polygon data'
    elif sdtstype == 'Entity point':
        resource_type = 'Point data'
    else:
        resource_type = ''
        issues.append((fname, f'unmapped resource type: direct={direct!r} sdtstype={sdtstype!r}'))

    # --- Rights / Rights Holder ---
    useconst = text(idinfo.find('useconst'))
    cntorg = text(distinfo.find('.//cntorg')) if distinfo is not None else ''

    # --- Spatial Coverage ---
    spatial = []
    for p in idinfo.findall('keywords/place'):
        spatial += [text(k) for k in p.findall('placekey')]

    # --- Subject ---
    subjects = []
    for t in idinfo.findall('keywords/theme'):
        kt = text(t.find('themekt'))
        if kt not in ('ISO 19115 Topic Category', 'None'):
            subjects += [text(k) for k in t.findall('themekey')]

    # --- Theme ---
    themes = []
    for t in idinfo.findall('keywords/theme'):
        kt = text(t.find('themekt'))
        if kt == 'ISO 19115 Topic Category':
            themes += [text(k) for k in t.findall('themekey')]

    # --- WxS Identifier ---
    wxs_id = f'sde:columbia.{rid}' if is_public and rid else ''

    row = {
        'Title': title,
        'Bounding Box': envelope,
        'Creator': pipe(creators),
        'Date Issued': pubdate,
        'Date Range': date_range,
        'Description': abstract,
        'File Size': filesize,
        'Format': formname,
        'Geometry': envelope,
        'Georeferenced': georeferenced,
        'ID': rid,
        'Index Year': pipe(index_years),
        'Keyword': pipe(keywords),
        'Language': pipe(languages),
        'Metadata Version': 'Aardvark',
        'Modified': MODIFIED_TS,
        'Provider': 'Columbia',
        'Publisher': publisher,
        'Resource Class': resource_class,
        'Resource Type': resource_type,
        'Rights': useconst,
        'Rights Holder': cntorg,
        'Spatial Coverage': pipe(spatial),
        'Subject': pipe(subjects),
        'Suppressed': 'false',
        'Theme': pipe(themes),
        'Access Rights': access_rights,
        'WxS Identifier': wxs_id,
    }
    if not rid:
        issues.append((fname, 'no id (resdesc) - record skipped'))
        continue
    resource_rows.append(row)

    # --- Distributions ---
    # download must always be a labeled array per Aardvark/GBL 3.0 spec, even for one file;
    # label is the button text shown in GeoBlacklight, so use the record's Format.
    onlink = text(citeinfo.find('onlink')) if citeinfo is not None else ''
    if onlink:
        dist_rows.append({'ID': rid, 'Type': 'download', 'URL': onlink, 'Label': formname})
    else:
        issues.append((fname, 'no onlink for distributions'))

    dashed_id = rid.replace('_', '-')
    dist_rows.append({'ID': rid, 'Type': 'url', 'URL': GBL_BASE + dashed_id, 'Label': ''})

    if is_public:
        dist_rows.append({'ID': rid, 'Type': 'wfs', 'URL': WFS_URL, 'Label': ''})
        dist_rows.append({'ID': rid, 'Type': 'wms', 'URL': WMS_URL, 'Label': ''})

with open(RESOURCES_OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=RESOURCE_COLUMNS)
    w.writeheader()
    w.writerows(resource_rows)

with open(DISTRIBUTIONS_OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['ID', 'Type', 'URL', 'Label'])
    w.writeheader()
    w.writerows(dist_rows)

print('resource rows:', len(resource_rows))
print('distribution rows:', len(dist_rows))
print('issues:', len(issues))
for i in issues[:40]:
    print(' ', i)
