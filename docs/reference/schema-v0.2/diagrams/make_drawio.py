from xml.etree import ElementTree as ET
from xml.dom import minidom
from html import escape
from pathlib import Path

OUT=Path(__file__).parent/'Mon-Edupreneur-Schema-v0.2.drawio'
root=ET.Element('mxfile', {'host':'app.diagrams.net','modified':'2026-11-21T22:00:00.000Z','agent':'Mon Edupreneur Architecture','version':'24.7.17','type':'device'})
C={'identity':('#E7F6EC','#65AA86'),'curriculum':('#EEF4FF','#7D9FDD'),'publication':('#FFF6E0','#D5AD55'),'sync':('#F3EEFF','#AA90D5'),'ops':('#F2F4F7','#9BA3AE'),'external':('#FFFFFF','#BBC1CA')}

def page(pid,name,title,nodes,edges,notes=''):
 d=ET.SubElement(root,'diagram',{'id':pid,'name':name})
 model=ET.SubElement(d,'mxGraphModel',{'dx':'1000','dy':'650','grid':'1','gridSize':'10','guides':'1','tooltips':'1','connect':'1','arrows':'1','fold':'1','page':'1','pageScale':'1','pageWidth':'1350','pageHeight':'850','math':'0','shadow':'0'})
 graph=ET.SubElement(model,'root'); ET.SubElement(graph,'mxCell',{'id':'0'});ET.SubElement(graph,'mxCell',{'id':'1','parent':'0'})
 def text_node(id,value,x,y,w,h,size=21,color='#12303D'):
  c=ET.SubElement(graph,'mxCell',{'id':id,'value':value,'style':f'text;html=1;whiteSpace=wrap;align=left;verticalAlign=middle;fontSize={size};fontColor={color};fontStyle=1;','vertex':'1','parent':'1'})
  ET.SubElement(c,'mxGeometry',{'x':str(x),'y':str(y),'width':str(w),'height':str(h),'as':'geometry'})
 text_node('title',title,40,14,1250,36,22)
 if notes: text_node('subtitle',notes,40,52,1250,27,12,'#526674')
 for id, label, details,kind,x,y,w,h in nodes:
  fill,stroke=C[kind]; val=f'<div style="font-size:15px;font-weight:700">{escape(label)}</div><div style="font-size:11px;color:#3b4b58;padding-top:4px">'+'<br/>'.join(escape(s) for s in details)+'</div>'
  c=ET.SubElement(graph,'mxCell',{'id':id,'value':val,'style':f'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=2;spacing=11;align=left;verticalAlign=middle;shadow=0;','vertex':'1','parent':'1'})
  ET.SubElement(c,'mxGeometry',{'x':str(x),'y':str(y),'width':str(w),'height':str(h),'as':'geometry'})
 for idx,(child,parent) in enumerate(edges,1):
  c=ET.SubElement(graph,'mxCell',{'id':f'e{idx}','edge':'1','parent':'1','source':child,'target':parent,'style':'edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#6E8194;strokeWidth=1.6;endArrow=block;endFill=1;endSize=7;','value':''})
  ET.SubElement(c,'mxGeometry',{'relative':'1','as':'geometry'})

page('erd01','01 Curriculum','Mon Edupreneur 2.0 — Curriculum ERD',[
 ('grades','grades',['PK id','UNIQUE code / sort_order','labels jsonb'],'curriculum',55,125,220,100),
 ('subjects','subjects',['PK id','UNIQUE slug','labels jsonb'],'curriculum',55,325,220,100),
 ('courses','courses',['PK id','FK grade_id / subject_id','UNIQUE grade+subject+slug'],'curriculum',360,215,235,110),
 ('units','units',['PK id','FK course_id','UNIQUE course+position'],'curriculum',670,130,215,105),
 ('lessons','lessons',['PK id','FK unit_id','UNIQUE unit+position'],'curriculum',975,130,215,105),
 ('revs','lesson_revisions',['PK id','FK lesson_id','UNIQUE lesson+locale+revision','status + blocks jsonb'],'publication',950,355,270,125),
 ('questions','question_revisions',['PK id','FK lesson_revision_id','UNIQUE revision+question_key','answer_key jsonb'],'publication',950,595,270,125),
 ('learners','learner_profiles',['PK / FK user_id → auth.users','FK grade_id','preferred_locale fr / ht'],'identity',355,585,250,110),
],[('courses','grades'),('courses','subjects'),('units','courses'),('lessons','units'),('revs','lessons'),('questions','revs'),('learners','grades')],'Arrows: child record → referenced parent. Key fields shown; full columns in the SQL migration.')

page('erd02','02 Publication','Mon Edupreneur 2.0 — Review & Publication ERD',[
 ('staff','staff_roles',['PK user_id + role','reviewer / editor / publisher'],'identity',65,100,250,95),
 ('rev','lesson_revisions',['PK id','status = approved','immutable after approval'],'publication',65,335,250,105),
 ('source','content_sources',['PK id','rights_status must be cleared'],'publication',65,610,250,100),
 ('reviews','editorial_reviews',['PK id','FK lesson_revision_id','FK reviewer_id'],'publication',405,100,255,115),
 ('links','lesson_revision_sources',['PK revision_id + source_id','both columns FK'],'publication',405,560,255,105),
 ('items','pack_items',['PK pack_release_id + lesson_revision_id','UNIQUE release+position'],'publication',725,320,265,120),
 ('release','pack_releases',['PK id','UNIQUE pack_key+locale+revision','manifest hash + bytes'],'publication',1060,180,250,115),
 ('current','pack_current',['PK pack_key + locale','FK release_id (active only)'],'publication',1060,480,250,105),
],[('reviews','rev'),('reviews','staff'),('links','rev'),('links','source'),('items','rev'),('items','release'),('current','release')],'Approved content, review and source rights are checked before a release is activated.')

page('erd03','03 Offline Sync','Mon Edupreneur 2.0 — Learning & Offline Sync ERD',[
 ('learners','learner_profiles',['PK user_id','Auth subject + grade'],'identity',45,135,235,100),
 ('lesson','lessons',['PK id','stable lesson identity'],'curriculum',45,370,235,100),
 ('question','question_revisions',['PK id','immutable published question'],'curriculum',45,600,235,105),
 ('progress','lesson_progress',['PK learner_id + lesson_id','FK last_revision_id','completed_at / read position'],'sync',365,255,255,120),
 ('attempts','practice_attempts',['PK id','UNIQUE learner_id + op_id','FK question_revision_id'],'sync',365,540,255,125),
 ('state','account_sync_state',['PK learner_id','current_version bigint'],'sync',715,135,250,105),
 ('receipts','sync_receipts',['PK learner_id + op_id','payload SHA-256 / result'],'sync',715,385,250,110),
 ('feed','account_change_feed',['PK learner_id + version','change_data jsonb'],'sync',1045,135,260,110),
 ('sqlite','Mobile SQLite (client)',['local outbox','saved lessons & progress','not a server table'],'external',1045,515,260,130),
],[('progress','learners'),('progress','lesson'),('attempts','learners'),('attempts','question'),('state','learners'),('receipts','learners'),('feed','state')],'Each offline operation is committed locally, then sent with a stable op_id. ACK only after server commit.')

raw=ET.tostring(root,encoding='utf-8')
OUT.write_bytes(b"<?xml version='1.0' encoding='utf-8'?>\n"+raw)
print(str(OUT),OUT.stat().st_size,'bytes')
