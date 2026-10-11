"""Fast, bounded workbook parsing for Letterdesk.

Required input columns:
Author | Email | Subject | First Message

Only these four fields are required. Additional columns are ignored unless they
match an optional alias used to enrich the Author Scout record.
"""
import csv
import io
import re
import zipfile
from itertools import islice
from openpyxl import load_workbook

REQUIRED_COLUMNS = "Author, Email, Subject, First Message"

ALIASES = {
 'id':['Author Scout ID','Canonical Author ID','Source Row ID','Original Row','Original Row ID'],
 'name':['Author','Author Name','Name','Author Name — Verified','Author Name — Bot'],
 'email':['Email','Contact Email','Verified Email','Public Contact Email','Public Email','Public Professional Email','Verified Public Email','Author Email','Public Professional Email — Bot','Recorded Email','Public recorded contact','Public Recorded Contact','Recipient Email','Email Address','To'],
 'website':['Website / Profile','Website','Official Website','Verified Official Website','Author Website'],
 'email_source_url':['Email Source','Email Source URL','Exact Email Source URL','Contact Source','Primary Research Source','Primary Source URL','Source URL'],
 'country':['Country','Country Verified','Country / Market'],
 'genre':['Genre','Genre / Category'],
 'subject':['Subject','Selected Subject','Subject Line','Subject Option 1','Final Subject','Personalized subject','Personalized Subject'],
 'body':['First Message','First Outreach Message','Best First Message — Author Language','First Outreach Message (Icelandic)','First Message (Author Language)','Personalized Message (Author Language)','First Message (Icelandic)','Icelandic Message','Agent-Style First Message','Full First Message','Personalized First Message','Message','Body','Email Body','Author-language Message','Author Language Message','Author-language first message','Author Language First Message','Primary Message'],
 'body_english':['First Message (English)','English Version','Best First Message — English','First Outreach Message (English)','Personalized First Message (English)','English Message','English Review','English Review Message','English Translation','English review version','English Review Version'],
 'bio':['Short Bio','Research Summary','Verified Research Summary','Bio','Biography','Researched Bio'],
 'books':['Key Works','Books','Main Books','Key Work Referenced','Book/Work Referenced','Books / Works','Earlier work','Earlier Work'],
 'recent_activity':['Recent Activity / Current Moment','Recent Activity','Current Moment','2026 Activity Evidence','Updated evidence / research finding','Updated Evidence / Research Finding'],
 'status':['Outreach Stage','Outreach Status','Processing Status','Research Status','Status','Readiness / Hold','Send gate','Send Gate'],
 'reply_notes':['Reply / Conversation Notes','Conversation Notes','Research Notes'],
}

def norm(value):
 return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()

def _column_map(raw_header):
 header=[norm(x) for x in raw_header]
 return {k:next((header.index(norm(a)) for a in names if norm(a) in header),None) for k,names in ALIASES.items()}

def _valid_header(columns):
 return all(columns.get(k) is not None for k in ('name','email','subject','body'))

def _rows_from_table(title, table):
 if not table: return None
 columns=None;header_row=0
 for header_row,raw_header in enumerate(table[:20]):
  candidate=_column_map(raw_header)
  if _valid_header(candidate):
   columns=candidate;break
 if columns is None:return None
 if len(table)-header_row>5001: raise ValueError('Use at most 5,000 rows per upload.')
 rows=[];issues=[];seen=set()
 for number,raw in enumerate(table[header_row+1:],header_row+2):
  if not any(v is not None and str(v).strip() for v in raw):continue
  item={k:(str(raw[i]).strip() if i is not None and i<len(raw) and raw[i] is not None else '') for k,i in columns.items()}
  item['email']=item['email'].lower()
  item['row']=number
  reason=''
  if not item['name']: reason='Missing author'
  elif not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+',item['email']) or len(item['email'])>254: reason='Missing or invalid email'
  elif not item['subject']: reason='Missing subject'
  elif not item['body']: reason='Missing first message'
  elif '\n' in item['subject'] or '\r' in item['subject']: reason='Subject must be one line'
  elif len(item['subject'])>400 or any(len(item[k])>30000 for k in ('body','body_english','bio','books','reply_notes')): reason='Text exceeds field limit'
  elif any(norm(item['status']).startswith(x) for x in ('sent','replied','on hold','hold','do not contact','unsubscribed','deprioritized','deprioritised')) or 'duplicate hold' in norm(item['status']): reason='Excluded by status: '+item['status']
  identity=norm(item['name'])+'|'+norm(item['country'])
  if not reason and identity in seen: reason='Duplicate author in this workbook'
  if reason:
   issues.append({'row':number,'name':item['name'],'reason':reason})
   continue
  seen.add(identity);rows.append(item)
 return {'sheet':title,'rows':rows,'issues':issues,'columns':{k:str(table[header_row][i]) for k,i in columns.items() if i is not None}}

def parse_upload(data, filename):
 if len(data)>15*1024*1024: raise ValueError('Required columns: '+REQUIRED_COLUMNS)
 lower=filename.lower()
 if lower.endswith('.csv'):
  try:
   table=list(islice(csv.reader(io.StringIO(data.decode('utf-8-sig'))),5022))
  except UnicodeError:
   raise ValueError('Required columns: '+REQUIRED_COLUMNS)
  parsed=_rows_from_table('CSV',table)
  if parsed:return parsed
  raise ValueError('Required columns: '+REQUIRED_COLUMNS)

 if not lower.endswith(('.xlsx','.xlsm')):
  raise ValueError('Required columns: '+REQUIRED_COLUMNS)

 try:
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   if sum(f.file_size for f in z.infolist())>80*1024*1024:
    raise ValueError('Required columns: '+REQUIRED_COLUMNS)
  book=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
  try:
   # Scan only the first 20 rows of each sheet to find the Letterdesk table.
   # Once found, parse only that sheet instead of materialising every worksheet.
   for sheet in book.worksheets:
    if sheet.max_row and sheet.max_row>5020: continue
    if sheet.max_column and sheet.max_column>150: continue
    head=list(islice(sheet.iter_rows(values_only=True),20))
    header_index=None;columns=None
    for idx,raw_header in enumerate(head):
     candidate=_column_map(raw_header)
     if _valid_header(candidate):
      header_index=idx;columns=candidate;break
    if columns is None:continue

    table=head[:header_index+1]
    remaining=islice(sheet.iter_rows(min_row=header_index+2,values_only=True),5000)
    table.extend(remaining)
    return _rows_from_table(sheet.title,table)
  finally:
   book.close()
 except ValueError:
  raise
 except Exception:
  raise ValueError('Required columns: '+REQUIRED_COLUMNS)

 raise ValueError('Required columns: '+REQUIRED_COLUMNS)
