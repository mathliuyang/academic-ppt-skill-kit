import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {isAbsolute, resolve} from 'node:path';
const modules=process.env.RUNTIME_NODE_MODULES || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
if (!modules) throw new Error('先从依赖加载器设置 RUNTIME_NODE_MODULES');
const require=createRequire(resolve(modules, '..', '__academic_ppt_loader.cjs'));
const {Presentation,PresentationFile}=await import(require.resolve('@oai/artifact-tool'));
const p=Presentation.create({slideSize:{width:1280,height:720}}), blue='#005AA6', bar='#0070C0', red='#C00000', pale='#D2DEEF', white='#FFFFFF', ink='#000000';
const out=process.argv[2]; if (!out || !isAbsolute(out)) throw new Error('请传入绝对输出目录');
function rect(s,x,y,w,h,fill,line='none',stroke=0){return s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,line:{style:'solid',fill:line,width:stroke}})}
function txt(s,t,x,y,w,h,pt=20,col=ink,bold=false,align='left'){let q=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{style:'solid',fill:'none',width:0}});q.text=t;q.text.style={typeface:'Microsoft YaHei',fontSize:pt*96/72,color:col,bold,alignment:align,verticalAlignment:'middle',wrap:'square',autoFit:'shrinkText',insets:3};return q}
function header(s,t,n){s.background.fill=white;txt(s,t,51,19,1143,61,32,blue,true,'center');rect(s,51,91,1178,3,blue);txt(s,''+n,1215,677,30,24,12,ink,false,'right')}
function section(s,x,y,w,label){rect(s,x,y,w,54,bar);txt(s,label,x+12,y+2,w-24,50,20,white,true)}
let s=p.slides.add();s.background.fill=white;rect(s,0,190,1280,184,bar);txt(s,'汇报题目\n研究内容与关键技术',50,197,1180,168,40,white,true,'center');txt(s,'汇报人：姓名',283,415,650,55,28,red,true,'center');txt(s,'单位：填写单位\n日期：填写日期',325,490,630,115,24,ink,false,'center');
s=p.slides.add();header(s,'一、研究背景及研究目标',2);
txt(s,'研究对象面临的主要问题与挑战',51,115,1178,60,26,blue,true,'center');
for(let i=0;i<3;i++){
  const y=175+i*146;
  rect(s,51,y+45,1178,81,'#F2F2F2',red,1);
  rect(s,51,y,141,47,red);
  txt(s,`挑战 ${i+1}`,57,y+2,130,43,24,white,true,'center');
  txt(s,['挑战一：概括研究对象的主要限制和形成原因。','挑战二：说明关键性能之间的矛盾及其实际影响。','挑战三：明确仍然缺少的证据或验证条件。'][i],65,y+49,1148,71,20,ink,true);
}
rect(s,51,620,1178,59,bar);txt(s,'以简洁的一句话总结背景中的核心矛盾',60,624,1160,51,24,white,true,'center');
s=p.slides.add();header(s,'二、拟解决的关键科学问题',3);rect(s,51,113,1178,195,'#EDF3F9');txt(s,'科学问题',65,130,230,60,28,blue,true,'center');txt(s,'用一两句话明确研究对象、关键矛盾和需要解决的问题。',298,128,905,150,24,blue,true);rect(s,51,331,1178,270,white,red,1);rect(s,51,331,63,270,red);txt(s,'主要\n难点',57,362,51,198,26,white,true,'center');txt(s,'难点一：具体原因与表现\n\n难点二：进一步的约束或机制',140,351,1030,210,24,ink,true);
s=p.slides.add();header(s,'三、研究内容与技术方案',4);const xs=[51,468,868], ws=[377,361,361];for(let i=0;i<3;i++){section(s,xs[i],115,ws[i],`${i+1}. 研究内容`);rect(s,xs[i],169,ws[i],276,white,'#A6A6A6',1);txt(s,'放置原图或流程',xs[i]+12,265,ws[i]-24,55,20,blue,false,'center');txt(s,'图注或方法说明',xs[i]+7,454,ws[i]-14,33,12.4,ink,true,'center')}rect(s,51,515,1178,161,'#E9F2FA',blue,1);rect(s,51,530,60,130,bar);txt(s,'方\n案',58,545,46,96,20,white,true,'center');txt(s,'■  关键方法与必要条件\n■  图中证据支持的结果\n■  进一步解释与联系',125,525,1085,140,20,ink,true);
s=p.slides.add();header(s,'研究结果：图文证据',5);for(let i=0;i<2;i++){let x=51+i*600;section(s,x,118,575,i?'结果二':'结果一');rect(s,x,172,575,315,white,'#A6A6A6',1);txt(s,'论文原图',x+10,290,555,50,20,blue,false,'center');txt(s,'图号',x+480,489,75,25,14,blue,false,'right');txt(s,'与本图对应的关键条件和结论。',x+8,530,555,100,20,ink)}
s=p.slides.add();header(s,'四、创新点及主要成果',6);for(let i=0;i<2;i++){let y=105+i*296;rect(s,51,y,1080,55,bar);txt(s,`创新点 ${i+1}——简洁说明核心贡献`,62,y+3,1054,49,20,white,true);rect(s,51,y+55,1178,220,white,'#8AB2D1',1);txt(s,'交代研究对象、方法和证据支持的关键结果。',72,y+79,760,155,20,ink);rect(s,875,y+80,320,155,'#F0F5F8','#B4CBDC',1);txt(s,'原图 / 对照',890,y+120,290,70,18,blue,false,'center')}
s=p.slides.add();header(s,'常用组件与取色卡',7);let pal=[['标题蓝','#005AA6','0, 90, 166'],['分栏蓝','#0070C0','0, 112, 192'],['强调红','#C00000','192, 0, 0'],['浅蓝底','#D2DEEF','210, 222, 239'],['黑色','#000000','0, 0, 0'],['白色','#FFFFFF','255, 255, 255']];for(let i=0;i<pal.length;i++){let x=51+(i%3)*400,y=120+Math.floor(i/3)*185;rect(s,x,y,365,95,pal[i][1],'#A6A6A6',1);txt(s,`${pal[i][0]}   ${pal[i][1]}\nRGB ${pal[i][2]}`,x,y+100,365,65,16,ink,false,'center')}txt(s,'色值对应本组件；主题色和透明度以实际页面为准。',51,555,1178,75,18,blue,false);
await fs.mkdir(out+'/build/render',{recursive:true});for(let i=0;i<p.slides.items.length;i++){let f=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(`${out}/build/render/slide-${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await f.arrayBuffer()));}
let f=await PresentationFile.exportPptx(p);await f.save(out+'/build/国自然组件库_候选.pptx');console.log('saved',p.slides.items.length);
