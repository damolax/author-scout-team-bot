"""Import and API regression checks; uses an isolated temporary database, no mail sent."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from letterdesk_import import parse_upload

folder=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+folder.name+'/test.db'
import bot_main_v3 as app
from fastapi.testclient import TestClient
app.legacy.init_db()
actor={'uid':101}
app._web_auth=lambda request:actor
app._auth_team=lambda ctx:{'id':1,'owner_user_id':ctx['uid']}
client=TestClient(app.app)

class LetterdeskTests(unittest.TestCase):
 def test_01_formatted_workbook(self):
  w=Workbook();s=w.active;s.append(['Title']);s.append([]);s.append(['Author','Contact Email','Subject','First Outreach Message (English)']);s.append(['Þór','thor@example.org','Halló','First line\nSecond line']);s.append(['Duplicate','thor@example.org','Hi','Duplicate']);s.append(['Missing','','Hi','Body'])
  b=io.BytesIO();w.save(b);r=parse_upload(b.getvalue(),'authors.xlsx')
  self.assertEqual(len(r['rows']),1);self.assertEqual(r['rows'][0]['body'],'First line\nSecond line');self.assertEqual([i['row'] for i in r['issues']],[5,6])
 def test_02_import_edit_reimport_and_isolation(self):
  data='Author,Email,Subject,First Message,First Message (English)\nTest Author,test@example.org,Hello,Original,English version\n'.encode()
  def upload(preview=False):return client.post('/api/v1/messages/import'+('?preview=true' if preview else ''),files={'file':('authors.csv',data,'text/csv')})
  actor['uid']=101
  r=upload(True);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['eligible'],1)
  self.assertEqual(app.legacy.rows('SELECT * FROM prospects'),[])
  r=upload();self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['created'],1)
  r=upload();self.assertEqual(r.json()['created'],0);self.assertEqual(len(app.legacy.rows('SELECT * FROM messages')),1)
  r=client.get('/api/v1/messages');self.assertEqual(r.status_code,200,r.text);m=r.json()['messages'][0];mid=m['id']
  draft={'recipient':'test@example.org','subject':'Edited','body':'Edited body','body_english':'English','reply_notes':'Note'}
  r=client.put(f'/api/v1/messages/{mid}',json=draft);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['message']['body'],'Edited body')
  actor['uid']=202
  self.assertEqual(client.put(f'/api/v1/messages/{mid}',json=draft).status_code,404)
  self.assertEqual(client.get('/api/v1/messages').json()['messages'],[])
  self.assertEqual(upload(True).json()['eligible'],0)
  actor['uid']=101
  client.post(f'/api/v1/messages/{mid}/status',json={'status':'sent'})
  self.assertEqual(upload().json()['ready'],0)
  draft['body']='Must not overwrite';draft['reply_notes']='Reply received'
  r=client.put(f'/api/v1/messages/{mid}',json=draft);self.assertEqual(r.json()['message']['body'],'Edited body');self.assertEqual(r.json()['message']['reply_notes'],'Reply received')
  self.assertEqual(client.get('/api/v1/messages?status=all&offset=100').json()['messages'],[])
 def test_03_bad_csv(self):
  with self.assertRaises(ValueError):parse_upload(b'Wrong,Columns\na,b','bad.csv')
  r=parse_upload(b'Author,Email,Subject,First Message,Status\nA,a@example.org,Hi,Body,Do not contact\nB,invalid,Hi,Body,Ready\n','a.csv')
  self.assertFalse(r['rows']);self.assertEqual(len(r['issues']),2)

if __name__=='__main__':unittest.main()
