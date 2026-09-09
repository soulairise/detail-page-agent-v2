"""사용자 승인 이미지를 주제별 JPEG와 카페24 HTML로 출력한다."""
from pathlib import Path
import json, html, hashlib, zipfile
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parent.parent
WORK=ROOT/'output/요가매트렌탈'
PLAN=json.loads((WORK/'기획/출력계획.json').read_text())
REVIEW=json.loads((WORK/'기획/이미지검토.json').read_text())
OUT=WORK/'최종출력'
FONT='/System/Library/Fonts/AppleSDGothicNeo.ttc'
INK='#193A38';MUTED='#506461';BG='#FAFBF8';GREEN='#DDE8DF';GOLD='#B69352'

def font(size,bold=False):return ImageFont.truetype(FONT,size,index=6 if bold else 4)

class Page:
 def __init__(self,section):
  self.s=section;self.h=section['height'];self.im=Image.new('RGB',(860,self.h),BG);self.d=ImageDraw.Draw(self.im);self.y=72;self.copy=[]
  self.text('SOULMAT  /  YOGA MAT RENTAL',size=20,color=MUTED)
  self.y+=35
 def text(self,text,size=31,color=INK,bold=False,width=740,x=60,gap=12):
  self.copy.append(text);f=font(size,bold)
  lines=[]
  for para in text.split('\n'):
   line=''
   for char in para:
    if self.d.textlength(line+char,font=f)>width and line:
     lines.append(line);line=char
    else:line+=char
   lines.append(line)
  for line in lines:
   self.d.text((x,self.y),line,font=f,fill=color,anchor='lt');self.y+=size+gap
  return self
 def title(self,kicker,title):
  self.text(kicker,22,GOLD,True);self.y+=12;self.text(title,54,INK,True,gap=14);self.y+=28;return self
 def space(self,n=26):self.y+=n;return self
 def photo(self,key,height=494):
  entry=next(x for x in REVIEW['images'] if x['id']==key)
  if not entry.get('approved'):raise ValueError('사용자 승인 없는 이미지: '+key)
  path=ROOT/entry['path']
  if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('승인 후 이미지 변경: '+key)
  im=Image.open(path).convert('RGB');im=ImageOps.fit(im,(860,height),method=Image.Resampling.LANCZOS)
  self.im.paste(im,(0,self.y));self.y+=height+18
  self.text('AI 연출 이미지 · 서비스 활용 예시',20,MUTED);self.y+=22;return self
 def card(self,number,title,body):
  start=self.y;self.d.rounded_rectangle((60,start,800,start+166),radius=10,fill=GREEN)
  self.y+=22;self.text(number,24,GOLD,True,x=82,width=60)
  self.y=start+20;self.text(title,32,INK,True,x=144,width=630)
  self.y+=6;self.text(body,26,MUTED,x=144,width=624,gap=8)
  if self.y>start+160:raise ValueError('카드 넘침: '+title)
  self.y=start+190;return self
 def row(self,label,value):
  self.text(label,29,INK,True);self.text(value,27,MUTED,gap=10);self.y+=16
  self.d.line((60,self.y,800,self.y),fill='#D8E0D9',width=2);self.y+=24;return self
 def end(self):
  if self.y>self.h-90:raise ValueError(f'{self.s["number"]} 내용 넘침: {self.y}/{self.h}')
  self.h=max(1200,min(self.h,((self.y+159)//20)*20))
  self.im=self.im.crop((0,0,860,self.h));self.d=ImageDraw.Draw(self.im)
  self.d.line((60,self.h-65,800,self.h-65),fill='#C9D5CC',width=2)
  self.d.text((60,self.h-43),'SOULMAT  ·  소울매트 요가매트 렌탈',font=font(18),fill=MUTED,anchor='lt')
  self.d.text((762,self.h-43),self.s['number'],font=font(18),fill=MUTED,anchor='lt')
  name=f'{self.s["number"]}_{PLAN["product_name"]}_{self.s["name"]}.jpeg'
  self.im.save(OUT/'images'/name,'JPEG',quality=95,subsampling=0,optimize=True)
  return {'file':'images/'+name,'width':860,'height':self.h,'alt':' '.join(self.copy),'content_bottom':self.y,'bytes':(OUT/'images'/name).stat().st_size}

def build():
 if not REVIEW.get('approval_source') or not all(i.get('approved') for i in REVIEW['images']):raise SystemExit('사용자 이미지 승인 후 실행해 주세요.')
 (OUT/'images').mkdir(parents=True,exist_ok=True)
 pages=[]
 p=Page(PLAN['sections'][0]).title('01  SERVICE','요가 클래스,\n매트부터 준비하세요')
 p.text('행사장부터 사내 클래스, 스튜디오 워크숍까지.\n필요한 수량과 일정에 맞춰 대여를 상담합니다.',29,MUTED).space(24).photo('event',530)
 p.text('행사 일자 · 장소 · 수량',42,INK,True).space(10)
 p.text('세 가지를 알려주시면 대여 가능 여부와\n배송·회수 조건을 함께 안내드립니다.',30,MUTED).space(40)
 p.text('요가매트 렌탈 문의',24,GOLD,True).text('0507-1316-1623',46,INK,True)
 pages.append(p.end())
 p=Page(PLAN['sections'][1]).title('02  SCENES','필요한 공간에,\n필요한 만큼')
 p.text('기업 웰니스 · 사내 요가',38,INK,True).space(8)
 p.text('사내 프로그램을 준비할 때,\n참여 인원과 공간에 맞춰 매트를 계획하세요.',29,MUTED).space(20).photo('office',560)
 p.space(12).text('스튜디오 · 원데이 워크숍',38,INK,True).space(8)
 p.text('특강이나 워크숍으로 추가 매트가 필요할 때,\n일정과 수량을 미리 상담해 주세요.',29,MUTED).space(22).photo('studio',560)
 p.text('사진 속 배치는 활용 예시입니다.\n실제 대여 색상·수량·구성은 상담 후 확정합니다.',27,MUTED)
 pages.append(p.end())
 p=Page(PLAN['sections'][2]).title('03  PROCESS','문의부터 회수까지,\n순서대로 확인합니다')
 for n,t,b in [('01','문의','행사 일자 · 장소 · 수량 전달'),('02','견적','대여기간과 배송·회수 조건 확인'),('03','일정 확정','가능 수량과 계약 조건 확인'),('04','반입','현장 반입 시간과 전달 방식 협의'),('05','행사 진행','협의한 기간 동안 사용'),('06','회수','약속한 일정과 방식으로 반납')]:p.card(n,t,b)
 pages.append(p.end())
 p=Page(PLAN['sections'][3]).title('04  CHECK POINT','매트 선택도,\n현장 준비도 꼼꼼하게')
 for n,t,b in [('01','수량','참가 인원과 예비 수량을 함께 전달'),('02','색상','희망 색상과 통일 여부를 상담'),('03','공간','실내·야외 여부와 바닥 상태 확인'),('04','반입 동선','엘리베이터·주차·하차 위치 공유')]:p.card(n,t,b)
 p.space(22).text('실제 대여 매트를 확인하세요',36,INK,True).space(12)
 p.text('두께·크기·소재·색상 구성과 세척·포장 방식은\n대여 전 실제 재고 기준으로 확인해 드립니다.',29,MUTED).space(28)
 p.text('활용 장면 이미지는 사양·재고·관리 상태를\n증명하는 실물 사진이 아닙니다.',25,MUTED)
 pages.append(p.end())
 p=Page(PLAN['sections'][4]).title('05  QUOTATION','견적에서 확인할\n여섯 가지 항목')
 for label,value in [('총 대여 비용','수량·대여기간·배송 조건을 확인한 뒤\n최종 견적서로 안내합니다.'),('대여기간 · 의무기간','반입일과 회수일을 기준으로\n계약서에 기재한 기간을 확인합니다.'),('배송·회수비','각 비용과 부담 주체, 추가 비용 발생 조건을\n계약 전에 확인합니다.'),('일정·수량 변경','변경 가능한 시점과 추가 비용 여부를\n견적 단계에서 협의합니다.'),('취소·중도해지 위약금','적용 여부와 산정 기준을 계약 전에 안내하고\n확정 계약서에 기재합니다.'),('파손·분실','사용 중 손상·분실에 대한 처리 기준과\n부담 범위를 미리 확인합니다.')]:p.row(label,value)
 p.space(20).text('금액과 조건은 상담 후 확정합니다.',28,INK,True)
 pages.append(p.end())
 p=Page(PLAN['sections'][5]).title('06  FAQ','문의 전에\n궁금한 점부터')
 for label,value in [('하루 행사도 상담할 수 있나요?','행사 날짜와 필요한 기간을 알려주세요.\n반입·회수 일정을 함께 확인합니다.'),('수량은 언제 확정하나요?','날짜별 재고와 희망 수량을 확인한 뒤\n대여 가능 수량을 확정합니다.'),('지역 제한이 있나요?','행사 장소를 알려주시면 일정과 이동 조건을\n확인해 가능 여부를 안내합니다.'),('색상을 지정할 수 있나요?','희망 색상을 알려주세요. 실제 재고에 따라\n가능한 구성과 대안을 안내합니다.')]:p.row(label,value)
 p.space(25).text('행사 일자 · 장소 · 수량',35,INK,True).space(10)
 p.text('문의 0507-1316-1623',38,INK,True).space(8).text('상담에서 세부 조건을 확인해 주세요.',27,MUTED)
 pages.append(p.end())
 p=Page(PLAN['sections'][6]).title('07  INFORMATION','상품정보와\n사용 전 확인사항')
 for label,value in [('품명','소울매트 요가매트 렌탈'),('모델명 · 크기·치수 · 재질 · 색상','대여 예정 재고 기준으로 상담 시 확인'),('제조자 · 제조국 · 원산지','실제 제공 제품의 표시사항 기준으로 확인'),('수입판매원 · 문의','소울메이트 · 0507-1316-1623'),('품질보증기준 · A/S','실제 제공 제품과 확정 계약 조건에 따라\n상담 창구에서 안내')]:p.row(label,value)
 p.space(12).text('사용 시 유의사항',32,INK,True).space(6)
 p.text('사용 전 매트와 바닥의 상태를 확인해 주세요.\n관리 방법은 실제 제품 안내에 따라 주세요.\n사용 환경과 보관 상태에 따라 차이가 있습니다.',27,MUTED).space(26)
 p.text('일부 장면은 AI로 만든 활용 예시입니다.\n실제 납품 사진·고객 후기·실물 사양 증거가 아닙니다.',24,MUTED)
 pages.append(p.end())
 body='<div style="max-width:860px;width:100%;margin:0 auto;">\n'+''.join(f'<img src="{html.escape(p["file"])}" width="860" height="{p["height"]}" alt="{html.escape(p["alt"])}" style="display:block;width:100%;height:auto;border:0;margin:0;">\n' for p in pages)+'</div>'
 title='소울매트 요가매트 렌탈'
 (OUT/'소울매트_요가매트렌탈_카페24상세페이지.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><body style="margin:0">'+body+'</body></html>')
 (OUT/'소울매트_요가매트렌탈_카페24본문삽입.html').write_text(body)
 manifest={'product':title,'images':pages,'image_approval':REVIEW['approval_source'],'status':'과제 제출용 출력; 실판매 전 사양·거래조건·이미지 호스팅 경로 확인 필요','cafe24_image_base_url':None}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 (OUT/'사용안내.md').write_text('# 채널별 사용 안내\n\n카페24: images 폴더를 자사몰 이미지 저장소에 업로드한 뒤 본문삽입.html의 images/ 경로를 실제 HTTPS 이미지 경로로 치환하세요. 현재 HTML은 폴더 내 로컬 확인용으로 연결돼 있습니다.\n\n스마트스토어·쿠팡: images 폴더 JPEG를 파일명 순서(01~07)로 업로드하세요.\n\n실제 재고 사양·고시정보·거래조건은 사용자 최종 확인 전입니다. 미확인 값을 지어내지 않고 상담 확인으로 표기했습니다. 과제용 출력물 완성과 실판매 등록 승인은 구분합니다.\n')
 with zipfile.ZipFile(WORK/'소울매트_요가매트렌탈_채널별출력.zip','w',zipfile.ZIP_DEFLATED) as z:
  for file in OUT.rglob('*'):
   if file.is_file():z.write(file,file.relative_to(OUT))
 # 원본 출력물의 축소 모음: 캡처가 아닌 검토용 콘택트시트
 sheet=Image.new('RGB',(1204,560),'#E7ECE6')
 for i,p in enumerate(pages):
  im=Image.open(OUT/p['file']);im.thumbnail((166,520));sheet.paste(im,(i*172+3,10))
 sheet.save(WORK/'출력물_모아보기.jpg',quality=92)
 print(json.dumps([{'file':p['file'],'size':[p['width'],p['height']]} for p in pages],ensure_ascii=False,indent=2))

if __name__=='__main__':build()
