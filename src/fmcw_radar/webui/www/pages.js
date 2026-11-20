'use strict';
/* fmcw_radar GUI -- the pages beside the workbench (system diagram, band trade-off, sweep) and the pinned baseline.
   Like app.js this only draws: the stages, rows, points and verdicts come from /api (guispec describes, guiutil computes).
   Loaded before app.js; everything here is called after app.js has booted. */

const PAGES = [['workbench','工作台','Workbench'],['system','系统框图','System'],['bands','频段取舍','Bands'],['sweep','扫描','Sweep']];
function route(){ const h=(location.hash||'#workbench').slice(1); return PAGES.some(p=>p[0]===h) ? h : 'workbench'; }
function pnav(){ return PAGES.map(([k,zh,en])=>`<a href="#${k}" data-page="${k}" class="${S.page===k?'on':''}">${L(zh,en)}</a>`).join(''); }
const numv = v => v===null||v===undefined ? '—' : typeof v==='number' ? String(+v.toPrecision(7)).replace('-','−') : String(v);
function lineVal(ln){ if(ln.kind==='read') return ln.value===null||ln.value===undefined ? '—' : typeof ln.value==='number' ? f(ln.value,ln.digits) : String(ln.value); return numv(ln.value); }
function lineText(ln){ if(ln.kind==='note') return L(ln.zh,ln.en); const v=lineVal(ln); return `${L(ln.zh,ln.en)} ${v}${ln.unit&&v!=='—'?' '+ln.unit:''}`; }
const stale = sha => !!(S.run && sha && sha!==S.run.repro.config_sha256);
const stalePill = () => `<span class="pill warn">${L('属于上一组参数','from other settings')}</span>`;

// the run on screen is the linearised engine's stand-in for a cycle-accurate one still being computed
function previewBar(){
  const p=S.run && S.run.preview; if(!p) return '';
  const M=S.spec.metrics, E=S.spec.engines;
  return `<div class="previewbar span2" data-tab="results budget pn"><b>${L('预览','Preview')}</b><span>${L(`这是 ${E['chirp:'+p.shown].zh} 的结果,${E['chirp:'+p.final].zh} 算完自动换上。`,`This is the ${E['chirp:'+p.shown].en}; the ${E['chirp:'+p.final].en} replaces it when it is done.`)} ${L('还不是最终值的:','Not final yet: ')}${p.pending.map(k=>esc(L(M[k].zh,M[k].en))).join(L('、',', '))}${L(',以及鬼目标清单与 chirp 误差曲线;其余结论数两个引擎相同。','; also the ghost list and the chirp error curve. The other headline numbers are the same from either engine.')}</span></div>`;
}

/* ---------- jobs with progress: the sweep and the band table ---------- */
function kjobHtml(kind){
  const j=S.jobs[kind]; if(!j) return '';
  const p=j.progress; const pct = p&&p.total ? 100*p.done/p.total : 0;
  return `<div class="jobtxt"><span>${j.status==='queued'?L('排队中','queued'):L('计算中','running')}</span><span class="num">${p?`${p.done} / ${p.total}`:''} · ${f(j.elapsed_s||0,1)} s</span></div>
   <div class="bar"><i style="width:${pct.toFixed(1)}%"></i></div>
   <div class="jobtxt"><span>${L('每一步是一份完整的统计引擎报告','every step is a full statistical report')}</span><button class="btn sm" data-act="kcancel" data-kind="${kind}">${L('取消','Cancel')}</button></div>`;
}
async function startJob(kind, body){
  S.kmsg[kind]=null;
  const j=await api(kind, body);
  if(j.status==='error' || j.error){ S.kmsg[kind]=j.error||''; S.jobs[kind]=null; render(); return; }
  S.jobs[kind]=j; render(); pollK(kind);
}
async function pollK(kind){
  const j0=S.jobs[kind]; if(!j0) return;
  let j; try{ j=await api('jobs/'+j0.id); }catch(e){ return; }
  if(!S.jobs[kind] || S.jobs[kind].id!==j.id) return;
  S.jobs[kind]=j;
  if(j.status==='done'){ S.jobs[kind]=null; S[kind]=j.result; if(kind==='bands') S.bandsShown=j.config_sha256; render(); return; }
  if(j.status==='cancelled'){ S.jobs[kind]=null; S.kmsg[kind]=L(`已在 ${f(j.elapsed_s||0,1)} s 取消`,`cancelled at ${f(j.elapsed_s||0,1)} s`); render(); return; }
  if(j.status==='error'){ S.jobs[kind]=null; S.kmsg[kind]=j.error||''; render(); return; }
  const slot=document.getElementById('kjob-'+kind); if(slot) slot.innerHTML=kjobHtml(kind);
  setTimeout(()=>pollK(kind), 250);
}

/* ---------- the system diagram ---------- */
// where each stage sits on the 1400-wide sheet: x, y, width (height follows the number of lines; chan and tgt span both rows)
const SYSG = {ramp:[40,66,182], ref:[250,96,130], tdc:[410,66,182], lf:[622,81,158], dco:[808,66,210], mult:[1036,96,118], lo:[1184,66,186],
 split:[1198,340,158], pa:[640,340,196], txant:[440,340,164], comp:[392,228,260], leak:[440,436,164],
 chan:[214,340,200,294], tgt:[30,340,164,294], rxant:[440,524,164], mix:[640,524,196], hpf:[872,524,142], ifa:[1036,524,180], adc:[1226,524,156],
 rfft:[1190,702,182], dfft:[946,702,206], rd:[700,702,208], cfar:[454,702,208], det:[208,702,208], dbf:[30,702,140]};
function sysBlocks(){
  return S.run.system.stages.map(st=>{ const g=SYSG[st.id]; const h = g[3] || 28 + 15*st.lines.length + (st.out?24:0) + 4; return Object.assign({x:g[0], y:g[1], w:g[2], h}, st); });
}
// a line wider than its box -- a font other than the one this sheet was laid out in -- is squeezed to fit, never cut off
function fitSys(root){
  root.querySelectorAll('svg.sys .blk').forEach(g=>{ const r=g.querySelector('rect'); const x0=+r.getAttribute('x'), w=+r.getAttribute('width');
    const chips=[...g.querySelectorAll('.stag')].map(c=>{ const b=c.querySelector('rect'); return {y:+b.getAttribute('y')+10, x:+b.getAttribute('x')}; });
    const bv=g.querySelector('.bv');
    g.querySelectorAll('text.bl, text.bo, text.bt').forEach(t=>{ const y=+t.getAttribute('y'); const chip=chips.find(c=>Math.abs(c.y-y)<2);
      const end = chip ? chip.x-4 : (t.classList.contains('bt') && bv ? x0+w-16-bv.getComputedTextLength() : x0+w-8); const avail=end-(+t.getAttribute('x'));
      if(avail>0 && t.getComputedTextLength()>avail){ t.setAttribute('textLength', avail.toFixed(1)); t.setAttribute('lengthAdjust','spacingAndGlyphs'); } }); });
}
function sysTagSvg(path, x, y){
  const src=S.tags[path]; if(!src) return '';
  const w={spec:30, assumed:50, derived:46, survey:42}[src]||44; const key=(S.resolved[path]||{}).key||'';
  return `<g class="stag t-${src}" data-src="${src}" data-key="${key}" ${edited(path)?`data-extra="${path}"`:''} tabindex="0" role="button" aria-label="${src}"><rect x="${x-w}" y="${y-10}" width="${w}" height="13" rx="3"/><text x="${x-w/2}" y="${y}" text-anchor="middle">${src}</text></g>`;
}
function sysSvg(){
  const B=sysBlocks(); const g=Object.fromEntries(B.map(b=>[b.id,b])); const LN=S.spec.lanes; const W=1400, H=836; const rep=S.run.report;
  const cx=b=>b.x+b.w/2, cy=b=>b.y+b.h/2, rt=b=>b.x+b.w, bt=b=>b.y+b.h;
  let s=`<svg viewBox="0 -4 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${L('系统框图','system block diagram')}" class="sys">
   <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="ahf"/></marker>
   <marker id="ah2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="ahl"/></marker>
   <marker id="ah3" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="ahg"/></marker></defs>`;
  s+=`<rect x="20" y="22" width="1364" height="196" rx="10" class="lane l-gen"/><text x="24" y="14" class="lanecap c-gen">${L(LN.gen.zh,LN.gen.en)}</text>`;
  s+=`<rect x="20" y="326" width="1364" height="320" rx="10" class="lane l-rf"/><text x="1180" y="319" text-anchor="end" class="lanecap c-rf">${L(LN.rf.zh,LN.rf.en)}</text>`;
  s+=`<rect x="20" y="688" width="1364" height="134" rx="10" class="lane l-dsp"/><text x="34" y="682" class="lanecap c-dsp">${L(LN.dsp.zh,LN.dsp.en)}</text>`;
  const wire=(d,cls='',m='ah')=>`<path d="${d}" class="wire ${cls}" marker-end="url(#${m})"/>`;
  const lab=(x,y,zh,en,anchor='middle',cls='')=>`<text x="${x}" y="${y}" text-anchor="${anchor}" class="wl halo2 ${cls}">${L(zh,en)}</text>`;
  // the loop
  s+=wire(`M${rt(g.ref)} ${cy(g.ref)}H${g.tdc.x}`)+wire(`M${rt(g.tdc)} ${cy(g.lf)}H${g.lf.x}`)+wire(`M${rt(g.lf)} ${cy(g.lf)}H${g.dco.x}`)+wire(`M${rt(g.dco)} ${cy(g.mult)}H${g.mult.x}`)+wire(`M${rt(g.mult)} ${cy(g.mult)}H${g.lo.x}`);
  // two-point modulation: the ramp into the reference path and, directly, into the DCO
  s+=wire(`M${cx(g.ramp)} ${g.ramp.y}V50H${cx(g.tdc)}V${g.tdc.y}`,'acc','ah2')+wire(`M${cx(g.tdc)} 50H${cx(g.dco)}V${g.dco.y}`,'acc','ah2');
  s+=lab((cx(g.ramp)+cx(g.tdc))/2,46,'FCW 斜坡 → 参考路径','FCW ramp → reference path','middle','c-acc')
    +lab((cx(g.tdc)+cx(g.dco))/2,46,`直通路:增益 ${numv(S.run.values['lo.dp_gain'])} · 校准 ${S.run.values['lo.dp_cal']}`,`direct path: gain ${numv(S.run.values['lo.dp_gain'])} · calibration ${S.run.values['lo.dp_cal']}`,'middle','c-acc');
  const fx=rt(g.dco)+15;
  s+=wire(`M${fx} ${cy(g.mult)}V204H${cx(g.tdc)}V${bt(g.tdc)}`)+lab((fx+cx(g.tdc))/2,200,'反馈:DCO 相位回到 TDC','feedback: DCO phase back to the TDC');
  // the one LO: down to the splitter, to the transmitter and to the mixer
  s+=wire(`M${cx(g.split)} ${bt(g.lo)}V${g.split.y}`,'lo','ah2');
  s+=wire(`M${g.split.x} ${g.split.y+26}H${rt(g.pa)}`,'lo','ah2')+lab((g.split.x+rt(g.pa))/2,g.split.y+20,'发射支路','transmit branch','middle','c-acc');
  const ym=484; const pn=rep.phase_noise||{};
  s+=wire(`M${cx(g.split)} ${bt(g.split)}V${ym}H${cx(g.mix)}V${g.mix.y}`,'lo','ah2')
    +lab((cx(g.split)+cx(g.mix))/2+40,ym-6,`同一条 LO 去混频:相噪经 τ 相关抵消(LO ${f(pn.lo_rms_rad,4)} → 残余 ${f(pn.residual_rms_rad,4)} rad)`,`the same LO to the mixer: phase noise cancels over τ (LO ${f(pn.lo_rms_rad,4)} → residual ${f(pn.residual_rms_rad,4)} rad)`,'middle','c-acc');
  // transmit, leftwards; the echo, rightwards
  s+=wire(`M${g.pa.x} ${g.pa.y+40}H${rt(g.txant)}`)+wire(`M${g.txant.x} ${g.txant.y+40}H${rt(g.chan)}`)+wire(`M${g.chan.x} ${g.txant.y+40}H${rt(g.tgt)}`);
  s+=wire(`M${rt(g.tgt)} ${g.rxant.y+40}H${g.chan.x}`)+wire(`M${rt(g.chan)} ${g.rxant.y+40}H${g.rxant.x}`)+wire(`M${rt(g.rxant)} ${g.rxant.y+40}H${g.mix.x}`)+wire(`M${rt(g.mix)} ${g.mix.y+40}H${g.hpf.x}`)+wire(`M${rt(g.hpf)} ${g.hpf.y+40}H${g.ifa.x}`)+wire(`M${rt(g.ifa)} ${g.ifa.y+40}H${g.adc.x}`);
  s+=lab((g.chan.x+rt(g.tgt))/2,g.txant.y+33,'照射','out')+lab((g.chan.x+rt(g.tgt))/2,g.rxant.y+33,'回波','echo');
  // the compliance tap and the leakage path
  s+=`<path d="M${cx(g.txant)} ${g.txant.y}V${bt(g.comp)}" class="wire dash"/>`;
  s+=`<path d="M${cx(g.txant)} ${bt(g.txant)}V${g.leak.y}" class="wire dash ${g.leak.active?'leak':''}"/><path d="M${cx(g.txant)} ${bt(g.leak)}V${g.rxant.y}" class="wire dash ${g.leak.active?'leak':''}" marker-end="url(#ah3)"/>`;
  // into the processing lane, leftwards
  s+=wire(`M${cx(g.adc)} ${bt(g.adc)}V${g.rfft.y}`)+wire(`M${g.rfft.x} ${g.rfft.y+40}H${rt(g.dfft)}`)+wire(`M${g.dfft.x} ${g.dfft.y+40}H${rt(g.rd)}`)+wire(`M${g.rd.x} ${g.rd.y+40}H${rt(g.cfar)}`)+wire(`M${g.cfar.x} ${g.cfar.y+40}H${rt(g.det)}`);
  s+=`<path d="M${g.det.x} ${g.det.y+40}H${rt(g.dbf)}" class="wire dash" marker-end="url(#ah3)"/>`;
  for(const b of B){
    const v=b.verdict;
    s+=`<g class="blk b-${b.lane} ${b.active?'':'dashed off'} ${S.sys===b.id?'sel':''} ${b.active&&v===true?'vok':b.active&&v===false?'vbad':''}" data-act="sysblk" data-id="${b.id}" data-w="${b.w}" tabindex="0" role="button" aria-label="${esc(L(b.zh,b.en))}">
     <rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="8"/>
     <text x="${b.x+10}" y="${b.y+18}" class="bt">${L(b.zh,b.en)}</text>`;
    if(!b.active) s+=`<text x="${b.x+b.w-10}" y="${b.y+18}" text-anchor="end" class="bv">${L('未启用','off')}</text>`;
    else if(v===true||v===false) s+=`<text x="${b.x+b.w-10}" y="${b.y+18}" text-anchor="end" class="bv">${v?'✓':'✕'}</text>`;
    b.lines.forEach((ln,i)=>{ const y=b.y+36+15*i; s+=`<text x="${b.x+10}" y="${y}" class="bl">${esc(lineText(ln))}</text>`+(ln.kind==='control'?sysTagSvg(ln.path, b.x+b.w-7, y):''); });
    if(b.out) s+=`<line x1="${b.x+8}" x2="${b.x+b.w-8}" y1="${b.y+b.h-24}" y2="${b.y+b.h-24}" class="bsep"/><text x="${b.x+10}" y="${b.y+b.h-9}" class="bo">→ ${esc(lineText(b.out))}</text>`;
    s+='</g>';
  }
  return s+'</svg>';
}
const LVN = {tx_power:['发射机能发','transmitter can deliver'], conducted:['回退后(传导)','after backoff (conducted)'], eirp:['EIRP','EIRP'], p_r:['接收天线口 P_r','at the RX antenna, P_r'], adc:['ADC 输入','at the ADC']};
function levelsSvg(w){
  const lv=S.run.plots.levels; const n=lv.length; const compact=w<560; const k=S.run.report.compliance;
  const full = lv.some(p=>p.full_power!==null && Math.abs(p.full_power-p.now)>1e-9);
  const ml=46, mr=compact?14:120, mt=16, mb=compact?58:44; const pw=w-ml-mr, ph=compact?210:230; const H=ph+mt+mb;
  const all=lv.flatMap(p=>[p.now, p.full_power]).filter(v=>v!==null); const y1=30, y0=Math.floor((Math.min(...all)-8)/20)*20;
  const X=i=>ml+(i+0.5)/n*pw, Y=v=>mt+(y1-v)/(y1-y0)*ph;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="level diagram">`;
  for(let v=y0;v<=20;v+=20){ s+=`<line x1="${ml}" x2="${ml+pw}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${ml-6}" y="${Y(v)+3.5}" text-anchor="end">${f(v,0)}</text>`; }
  s+=`<text x="4" y="${mt-4}" style="font-size:10px">dBm</text>`;
  const fsd=S.run.values['rx.adc_fullscale_dbm'];
  s+=`<line x1="${X(n-1)-pw/10}" x2="${X(n-1)+pw/10}" y1="${Y(fsd)}" y2="${Y(fsd)}" class="lim"/><text x="${X(n-1)}" y="${Y(fsd)-5}" text-anchor="middle" class="halo" style="font-size:10px">${L('ADC 满幅','ADC full scale')} ${f(fsd,0)}</text>`;
  if(k.applies){ s+=`<line x1="${X(2)-pw/10}" x2="${X(2)+pw/10}" y1="${Y(k.limit_dbm)}" y2="${Y(k.limit_dbm)}" style="stroke:var(--ok);stroke-dasharray:4 3"/>`; if(!compact) s+=`<text x="${ml+pw+10}" y="${Y(k.limit_dbm)+4}" style="fill:var(--ok);font-size:10.5px">${L('EIRP 上限','EIRP limit')} ${f(k.limit_dbm,0)} dBm</text>`; }
  const line=(key,cls)=>`<polyline points="${lv.map((p,i)=>`${X(i)},${Y(p[key])}`).join(' ')}" class="lv ${cls}"/>`+lv.map((p,i)=>`<circle cx="${X(i)}" cy="${Y(p[key])}" r="3.5" class="lvd ${cls}"/>`).join('');
  if(full) s+=line('full_power','full');
  s+=line('now','bo');
  lv.forEach((p,i)=>{ const d=i>2?2:0; s+=`<text x="${X(i)}" y="${Y(p.now)+16}" text-anchor="middle" class="lbl halo" style="font-size:10.5px">${f(p.now,d)}</text>`; if(full && Math.abs(p.full_power-p.now)>1e-9) s+=`<text x="${X(i)}" y="${Y(p.full_power)-8}" text-anchor="middle" class="halo" style="font-size:10.5px;fill:var(--bad)">${f(p.full_power,d)}</text>`; });
  lv.forEach((p,i)=>{ const t=L(...LVN[p.id]); if(compact){ const q=t.split(/[((]/); s+=`<text x="${X(i)}" y="${mt+ph+16}" text-anchor="middle" style="font-size:10px">${q[0].trim()}</text>`+(q[1]?`<text x="${X(i)}" y="${mt+ph+29}" text-anchor="middle" style="font-size:10px">(${q[1]}</text>`:''); } else s+=`<text x="${X(i)}" y="${mt+ph+18}" text-anchor="middle">${t}</text>`; });
  return s+'</svg>';
}
function systemPage(){
  if(!S.run) return `<div class="sp-page"><div class="empty">${L('计算中…','computing…')}</div></div>`;
  const B=S.run.system.stages; const LN=S.spec.lanes, E=S.spec.engines; const ch=S.run.engines.find(e=>e.id.startsWith('chirp:')), st=S.run.engines.find(e=>e.id==='statistical');
  const rows=B.map(b=>`<tr class="${S.sys===b.id?'hl':''} ${b.active?'':'dim'}" data-act="sysblk" data-id="${b.id}"><td class="st"><i class="ld d-${b.lane}"></i>${L(b.zh,b.en)}${b.active?'':` <span class="oov">${L('未启用','off')}</span>`}</td><td>${b.lines.map(ln=>`<span class="sp">${esc(lineText(ln))} ${ln.kind==='control'?T(ln.path):''}</span>`).join('')}</td><td class="num so">${b.out?esc(lineText(b.out)):''}</td><td class="se hide-s">${L(LN[b.lane].by_zh,LN[b.lane].by_en)}</td></tr>`).join('');
  const erow=(id,extra)=>`<tr><td class="st">${L(E[id].zh,E[id].en)}</td><td>${L(E[id].does_zh,E[id].does_en)} ${L(E[id].covers_zh,E[id].covers_en)} ${extra||''}</td></tr>`;
  const full = S.run.plots.levels.some(p=>p.full_power!==null && Math.abs(p.full_power-p.now)>1e-9);
  return `<div class="sp-page">
   ${S.error?refusalBar():''}${previewBar()}
   <div class="card">
    <div class="hdr"><div><h2>${L('系统框图','System block diagram')}</h2>
    <p class="sub">${L('从 chirp 发生到检测结果的整条链:每一级写着它在当前参数下的数、出处标签和这一级之后的量。蓝线是同一条 LO——发射和混频用的是它的同一份相噪,这是相关抵消的来源。虚线框是当前没有启用的环节。点任一级,下表对应行高亮。','The whole chain from the chirp generator to the detections: every stage with its numbers under the current settings, their source tags and the quantity after it. The blue line is the one LO — transmit and mixer share its phase noise, which is where the correlation cancelling comes from. A dashed box is a stage not in play. Click a stage to highlight its row below.')}</p></div></div>
    <div class="sysscroll" tabindex="0"><div class="chart sysc" data-chart="sys"></div></div>
    <div class="legend" style="margin-top:10px">
     <span><i class="ld d-gen"></i>${L('chirp 发生器','chirp generator')}</span><span><i class="ld d-rf"></i>${L('射频链路与信道','RF chain and channel')}</span>
     <span><i class="ld d-dsp"></i>${L('数字处理','digital processing')}</span><span><i class="ld d-reg"></i>${L('合规检查','compliance check')}</span>
     <span><span class="sw-line" style="border-color:var(--accent);border-top-width:2.5px"></span>${L('同一条 LO','the one LO')}</span>
     <span><span class="sw-line" style="border-color:var(--muted-mark);border-top-style:dashed"></span>${L('可选路径与检查','optional paths and checks')}</span>
     <span>${tag('spec','','legend')} ${tag('assumed','','legend')} ${tag('derived','','legend')} ${L('出处标签,点开看引文','source tags, click for the citation')}</span>
    </div>
    <p class="sub sysnote" style="margin:8px 0 0">${L('窄屏上框图在自己的框里左右滑动;逐级参数表在下面。','On a narrow screen the diagram scrolls sideways inside its own frame; the stage table is below.')}</p>
   </div>
   <div class="sp2">
    <div class="card"><h2>${L('电平图:信号从发射机到 ADC','Level diagram: the signal from the transmitter to the ADC')}</h2>
     <p class="sub">${full?L('蓝:当前(已回退);红:发射机满功率。','Blue: now (backed off); red: the transmitter at full power.'):L('当前就是满功率,只有一条线。','The transmitter is at full power: one line.')}</p>
     <div class="chart" data-chart="levels"></div>
     <div class="legend">${full?`<span><span class="sw-line" style="border-color:var(--bad)"></span>${L('满功率','full power')}</span>`:''}<span><span class="sw-line" style="border-color:var(--accent)"></span>${L('当前','now')}</span></div></div>
    <div class="card"><h2>${L('三个引擎各算哪一段','Which engine computes which part')}</h2>
     <table class="tbl engtbl" style="margin-top:8px"><tbody>
      ${erow(ch.id, ch.vouches_for_spurs?'':`<span class="pill warn" style="font-size:11px">${L('不能背书杂散','cannot vouch for spurs')}</span>`)}
      ${erow('statistical', `<span class="num">${st.wall_s} s</span>`)}
      ${erow('time', S.frame?`<span class="num">${S.frame.wall_s} s</span>`:`<span class="pill neu" style="font-size:11px">${L('这组参数还没跑','not run for these settings')}</span>`)}
     </tbody></table></div>
   </div>
   <div class="card"><h2>${L('逐级参数表','Stage by stage')}</h2>
    <div class="tblwrap"><table class="tbl stages"><thead><tr><th>${L('环节','Stage')}</th><th>${L('参数与出处','Parameters and sources')}</th><th>${L('这一级之后','After this stage')}</th><th class="hide-s">${L('由谁算','Computed by')}</th></tr></thead><tbody>${rows}</tbody></table></div></div>
  </div>`;
}
function refusalBar(){ return `<div class="refusal"><b>${L('配置层不接受这组参数','The config refuses these settings')}</b><span>${esc(S.error.error)}</span><span class="spacer"></span><span style="color:var(--muted)">${L('下面仍是上一组合法参数的结果。','Below is still the last legal run.')}</span></div>`; }

/* ---------- the band trade-off ---------- */
function ensureBands(){
  if(!S.run || S.error || S.jobs.bands) return;
  const sha=S.run.repro.config_sha256;
  if(S.bandsFor===sha) return;
  S.bandsFor=sha; startJob('bands', {values:S.run.values});
}
const tierName = (r, id) => { const t=(r.tiers||[]).find(x=>x.tier===id); return L(TIERZH[id]||(t?t.label:id), t?t.label:id); };
function bandsSvg(w){
  const rows=S.bands.rows.filter(r=>r.ok); const compact=w<620;
  const lw=compact?0:190, gap=compact?0:24, mr=8; const pane=compact?(w-mr):(w-lw-gap-mr)/2;
  const rh=compact?64:34, top=compact?6:40; const H=top+rows.length*rh+12; const rx0=lw, dx0=compact?0:lw+pane+gap;
  const Rmax=nice(1.15*Math.max(...rows.map(r=>r.metrics.range_res_m*100))), Dmax=nice(1.15*Math.max(...rows.map(r=>Math.max(r.detection_range_m, r.metrics.max_range_m))));
  const XR=compact?(v=>4+v/Rmax*(pane-60)):(v=>rx0+v/Rmax*(pane-40)), XD=compact?(v=>4+v/Dmax*(pane-60)):(v=>dx0+v/Dmax*(pane-40));
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="${L('频段取舍','band trade-off')}">`;
  if(!compact){ s+=`<text x="${rx0}" y="12" class="lbl" style="font-size:11px">${L('距离分辨率 [cm] ← 越短越好','range resolution [cm] ← shorter is better')}</text><text x="${dx0}" y="12" class="lbl" style="font-size:11px">${L('能看多远 [m] → 越长越好','reach [m] → longer is better')}</text>`;
    for(let i=0;i<=5;i++){ const a=Rmax*i/5, b=Dmax*i/5; s+=`<line x1="${XR(a)}" x2="${XR(a)}" y1="${top-4}" y2="${H-12}" class="grid"/><text x="${XR(a)}" y="${top-10}" text-anchor="middle" style="font-size:9.5px">${numv(a)}</text><line x1="${XD(b)}" x2="${XD(b)}" y1="${top-4}" y2="${H-12}" class="grid"/><text x="${XD(b)}" y="${top-10}" text-anchor="middle" style="font-size:9.5px">${numv(b)}</text>`; } }
  rows.forEach((r,i)=>{ const y=top+i*rh; const res=r.metrics.range_res_m*100, ifr=r.metrics.max_range_m, det=r.detection_range_m;
    if(r.id===S.band) s+=`<rect x="0" y="${y-3}" width="${w}" height="${rh-2}" rx="6" style="fill:var(--accent-soft)"/>`;
    let yr=y+6, yd=y+6;
    if(compact){ s+=`<text x="4" y="${y+11}" class="lbl" style="font-size:11.5px">${esc(L(r.zh,r.en))} <tspan style="font-weight:400;fill:var(--muted)">· ${f(r.limit_dbm,0)} dBm</tspan></text>`; yr=y+20; yd=y+38; }
    else s+=`<text x="4" y="${y+15}" class="lbl" style="font-size:11.5px">${esc(L(r.zh,r.en))}</text><text x="4" y="${y+27}" style="font-size:10px">${numv(r.sweep_ghz[0])}–${numv(r.sweep_ghz[1])} GHz · ${L('上限','limit')} ${f(r.limit_dbm,0)} dBm</text>`;
    s+=`<rect x="${XR(0)}" y="${yr}" width="${Math.max(0,XR(res)-XR(0))}" height="10" rx="2" style="fill:var(--c4)"/><text x="${XR(res)+4}" y="${yr+9}" class="num" style="font-size:10.5px">${f(res,2)} cm</text>`;
    s+=`<line x1="${XD(ifr)}" x2="${XD(det)}" y1="${yd+5}" y2="${yd+5}" style="stroke:var(--muted-mark);stroke-dasharray:3 3;stroke-width:1.5"/><circle cx="${XD(det)}" cy="${yd+5}" r="3" style="fill:var(--panel);stroke:var(--muted-mark)"/>`;
    s+=`<rect x="${XD(0)}" y="${yd}" width="${Math.max(0,XD(Math.min(ifr,det))-XD(0))}" height="10" rx="2" style="fill:var(--accent)"/><text x="${XD(Math.min(ifr,det))+4}" y="${yd-1}" class="num" style="font-size:10.5px">${f(ifr,1)}</text><text x="${XD(det)+6}" y="${yd+9}" class="num" style="font-size:10px">${f(det,1)} m</text>`;
  });
  return s+'</svg>';
}
function bandsPage(){
  ensureBands();
  const B=S.bands; const busy=!!S.jobs.bands;
  const head=`<div class="hdr"><div><h2>${L('频段取舍','Band trade-off')} ${B&&!busy&&stale(S.bandsShown)?stalePill()+` <button class="btn sm" data-act="bandsrun">${L('重新计算','Compute again')}</button>`:''}</h2>
    <p class="sub">${L('47 CFR §15.255(c)(2)。每一行是一份真的配置:扫频移进那一段、声明那个场景、发射机回退到刚好压在治理档上限、帧周期拉到够档里要求的关断时间;其余都是当前参数。行里的数是那份配置自己的统计引擎报告。"用这一档"把参数表改成那一行。','47 CFR §15.255(c)(2). Each row is a real config: the sweep moved into that band, that scenario declared, the transmitter backed off just to the governing tier\'s limit, the frame period stretched to the off-time the tier asks; everything else as it is now. The numbers are that config\'s own statistical report. "Use this band" puts the form there.')}</p></div></div>`;
  if(busy || !B) return `<div class="bp">${S.error?refusalBar():''}<div class="card">${head}<div class="job" id="kjob-bands" style="max-width:420px">${busy?kjobHtml('bands'):`<div class="jobtxt"><span>${esc(S.kmsg.bands||L('等一份合法的参数。','waiting for a legal set of parameters.'))}</span></div>${S.run&&!S.error?`<button class="btn sm" data-act="bandsrun">${L('重新计算','Compute again')}</button>`:''}`}</div></div></div>`;
  if(!B.applies) return `<div class="bp">${S.error?refusalBar():''}<div class="card">${head}<div class="empty">${L('这条规则不适用于当前频段:','The rule does not apply to this band: ')}${esc(B.why||'')}</div></div>${bundledCard(B)}</div>`;
  const ok=B.rows.filter(r=>r.ok); if(!ok.some(r=>r.id===S.band)) S.band=ok.length?ok[0].id:null; const sel=ok.find(r=>r.id===S.band);
  const off=r=>r.off_time_required_s===null?L('不要求','none'):`≥ ${f(r.off_time_required_s*1000,1)} ms / 33 ms`;
  const fr=r=>r.max_frame_rate_hz===null?L('不限','no limit'):f(r.max_frame_rate_hz,1)+' /s';
  const over=r=>r.full_power_over_db>0?`<span style="color:var(--bad)">${L('超','over')} ${f(r.full_power_over_db,1)} dB</span>`:`${L('低','under')} ${f(-r.full_power_over_db,1)} dB`;
  const limTag=r=>{ const k='fcc15255.'+r.governing+'.peak_eirp_dbm'; return S.sources[k]?tag(S.sources[k].source,k):''; };
  const use=r=>Object.keys(r.apply).length?`<button class="btn sm" data-act="useband" data-band="${r.id}">${L('用这一档','Use this band')}</button>`:`<span class="pill neu">${L('当前','current')}</span>`;
  const bad=r=>`<tr class="dim"><td><b>${L(r.zh,r.en)}</b></td><td colspan="11"><span class="pill bad">${L('配置层不接受','refused by the config')}</span> ${esc(r.error)}</td></tr>`;
  return `<div class="bp">${S.error?refusalBar():''}
   <div class="card">${head}
    <div class="chart" data-chart="bands"></div>
    <div class="legend"><span><span class="sw-line" style="border-color:var(--c4);border-top-width:6px"></span>${L('距离分辨率','range resolution')}</span><span><span class="sw-line" style="border-color:var(--accent);border-top-width:6px"></span>${L('IF 带宽限定的距离','range the IF band allows')}</span><span><span class="sw-line" style="border-color:var(--muted-mark);border-top-style:dashed"></span>${L('SNR 限定的检测距离(Pd 0.9,不计 IF 带限)','SNR-limited detection range (Pd 0.9, the IF band not asked)')}</span></div>
   </div>
   <div class="card btable"><div class="tblwrap"><table class="tbl"><thead><tr><th>${L('扫频','Sweep')}</th><th>${L('治理档','Governing tier')}</th><th class="n">${L('上限','Limit')}</th><th class="n">${L('满功率','Full power')}</th><th class="n">${L('回退','Backoff')}</th><th class="n">${L('分辨率','Res.')}</th><th class="n">${L('格点 SNR','Cell SNR')}</th><th class="n">${L('检测距离','Det. range')}</th><th class="n">${L('IF 距离','IF range')}</th><th>${L('关断时间','Off-time')}</th><th class="n">${L('最高帧率','Max rate')}</th><th></th></tr></thead><tbody>
    ${B.rows.map(r=>!r.ok?bad(r):`<tr data-act="band" data-band="${r.id}" class="${r.id===S.band?'hl':''}"><td><b>${L(r.zh,r.en)}</b><br><span style="color:var(--faint);font-size:11px">${numv(r.sweep_ghz[0])}–${numv(r.sweep_ghz[1])} GHz · ${L('场景','scenario')}: ${r.scenario===null?L('未声明','not declared'):r.scenario}</span></td><td>${tierName(r,r.governing)}</td><td class="n">${f(r.limit_dbm,0)} dBm ${limTag(r)}</td><td class="n">${over(r)}</td><td class="n">${f(r.backoff_db,1)} dB</td><td class="n">${f(r.metrics.range_res_m*100,2)} cm</td><td class="n">${f(r.metrics.snr_cell_db,2)} dB</td><td class="n">${f(r.detection_range_m,1)} m</td><td class="n">${f(r.metrics.max_range_m,2)} m</td><td>${off(r)}</td><td class="n">${fr(r)}</td><td>${use(r)}</td></tr>`).join('')}
   </tbody></table></div></div>
   <div class="bcards">${B.rows.map(r=>!r.ok?`<div class="bcard"><b>${L(r.zh,r.en)}</b><div style="font-size:12px;margin-top:4px"><span class="pill bad">${L('配置层不接受','refused')}</span> ${esc(r.error)}</div></div>`:`<div class="bcard ${r.id===S.band?'sel':''}" data-act="band" data-band="${r.id}"><div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><b>${L(r.zh,r.en)}</b><span class="num">${f(r.limit_dbm,0)} dBm ${limTag(r)}</span></div>
     <div style="font-size:12px;color:var(--muted);margin:2px 0 6px">${tierName(r,r.governing)} · ${L('满功率','full power')} ${over(r)} · ${L('回退','backoff')} ${f(r.backoff_db,1)} dB</div>
     <dl class="kv"><dt>${L('分辨率','resolution')}</dt><dd>${f(r.metrics.range_res_m*100,2)} cm (${numv(r.sweep_ghz[0])}–${numv(r.sweep_ghz[1])} GHz)</dd><dt>${L('IF 距离','IF range')}</dt><dd>${f(r.metrics.max_range_m,2)} m</dd><dt>${L('检测距离','det. range')}</dt><dd>${f(r.detection_range_m,1)} m · SNR ${f(r.metrics.snr_cell_db,2)} dB</dd><dt>${L('关断','off-time')}</dt><dd>${off(r)} · ${fr(r)}</dd></dl><div style="margin-top:8px">${use(r)}</div></div>`).join('')}</div>
   <div class="bp2">
    ${sel?`<div class="card"><h2>${L('选中:','Selected: ')}${L(sel.zh,sel.en)}</h2><p class="sub">${L('治理档 = 能用的档里上限最高的;实心绿 = 治理档,灰 = 可用,虚框 = 不可用。','Governing = highest limit among usable tiers; solid green = governing, grey = usable, dashed = not usable.')}</p><div class="chart" data-chart="btiers"></div><p class="sub" style="margin-top:8px">${esc(sel.verdict)}</p></div>`:''}
    <div class="card"><h2>${L('上限下的天线增益','Antenna gains under the limit')}</h2><p class="sub">${L('当前扫频,发射机满功率,单格 SNR。EIRP 压到上限之后,发射天线的增益不再影响 SNR;接收天线一 dB 换一 dB。','The sweep as configured, the transmitter at full power, SNR of one cell. Once the EIRP is held to the limit the transmit antenna\'s gain stops moving the SNR; the receive antenna moves it dB for dB.')}</p>
     <div class="tblwrap"><table class="tbl"><thead><tr><th class="n">TX dBi</th><th class="n">RX dBi</th><th class="n">${L('满功率 EIRP','full EIRP')}</th><th class="n">${L('按上限','at limit')}</th><th class="n">SNR ${L('满','full')}</th><th class="n">SNR ${L('上限','limit')}</th></tr></thead><tbody>
     ${B.antenna.map(a=>`<tr><td class="n">${numv(a.tx_gain_dbi)}</td><td class="n">${numv(a.rx_gain_dbi)}</td><td class="n">${f(a.full_power_eirp_dbm,1)}</td><td class="n">${f(a.eirp_at_limit_dbm,1)}</td><td class="n">${f(a.snr_full_power_db)}</td><td class="n"><b>${f(a.snr_at_limit_db)}</b></td></tr>`).join('')}</tbody></table></div></div>
   </div>
   ${bundledCard(B)}
  </div>`;
}
function bundledCard(B){
  if(!B.bundled.length) return '';                        // an installed wheel ships no config files
  return `<div class="card"><h2>${L('随库配置的现状','Bundled configs as they are')}</h2>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${L('配置','Config')}</th><th>${L('判定','Verdict')}</th></tr></thead><tbody>
    ${B.bundled.map(c=>`<tr><td><span class="mono">${c.config}</span><br><span style="color:var(--muted);font-size:11.5px">${c.n_tx>1?L(`${c.n_tx} 路 TDM 轮流`,`${c.n_tx} TX in turn (TDM)`):'1 TX'}${c.eirp_dbm!==null?` · EIRP <span class="num">${f(c.eirp_dbm,1)} dBm</span>`:''}</span></td><td>${c.applies?`<span class="pill ${c.compliant?'ok':'bad'}">${c.compliant?'✓':'✕'}</span> ${esc(c.verdict)}`:`<span class="pill neu">${L('不适用','n/a')}</span> ${esc(c.why)}`}</td></tr>`).join('')}</tbody></table></div></div>`;
}

/* ---------- the sweep ---------- */
function swCtl(){ return S.spec.controls.find(c=>c.path===S.sw.path); }
// the ends the form starts with: half to twice the current value, inside the control's display range
function swEnds(){ const c=swCtl(); const cur=shown(c).v; const ok=typeof cur==='number' && cur>0;
  return {lo: S.sw.lo!==null ? S.sw.lo : ok ? Math.max(c.lo, +(cur/2).toPrecision(6)) : c.lo, hi: S.sw.hi!==null ? S.sw.hi : ok ? Math.min(c.hi, +(cur*2).toPrecision(6)) : c.hi}; }
function sweepSvg(w){
  const R0=S.sweep, m=S.spec.metrics[S.sw.metric]; const sc=R0.scale;
  const P=R0.points.map(p=>({x:p.x/sc, ok:p.ok, y:p.ok ? (typeof p.metrics[S.sw.metric]==='boolean' ? +p.metrics[S.sw.metric] : p.metrics[S.sw.metric]) : null, band:p.in_if_band, err:p.error, raw:p.x}));
  const ys=P.filter(p=>p.y!==null && p.y!==undefined).map(p=>p.y); const xs=P.map(p=>p.x);
  const ml=58, mr=16, mt=14, mb=44; const pw=w-ml-mr, ph=Math.min(300, Math.max(190, w*0.36)); const H=ph+mt+mb;
  const x0=Math.min(...xs), x1=Math.max(...xs); let y0=ys.length?Math.min(...ys):0, y1=ys.length?Math.max(...ys):1; if(y0===y1){ y0-=1; y1+=1; } const pad=(y1-y0)*0.08; y0-=pad; y1+=pad;
  const X=v=>ml+(x1===x0?0.5:(v-x0)/(x1-x0))*pw, Y=v=>mt+(y1-v)/(y1-y0)*ph;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="${L('扫描','sweep')}">`;
  const st=nice((y1-y0)/5); for(let v=Math.ceil(y0/st)*st; v<=y1+1e-12; v+=st){ s+=`<line x1="${ml}" x2="${ml+pw}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${ml-6}" y="${Y(v)+3.5}" text-anchor="end">${numv(+v.toPrecision(6))}</text>`; }
  const sx=nice((x1-x0)/(w<520?4:8)); for(let v=Math.ceil(x0/sx)*sx; v<=x1+1e-12; v+=sx){ s+=`<line x1="${X(v)}" x2="${X(v)}" y1="${mt}" y2="${mt+ph}" class="grid"/><text x="${X(v)}" y="${mt+ph+15}" text-anchor="middle">${numv(+v.toPrecision(6))}</text>`; }
  s+=`<text x="${ml+pw/2}" y="${H-6}" text-anchor="middle">${esc(L(R0.zh,R0.en))}${R0.unit?` [${esc(R0.unit)}]`:''}</text><text x="4" y="${mt-2}" style="font-size:10px">${esc(L(m.zh,m.en))}${m.unit?` [${m.unit}]`:''}</text>`;
  const cur=R0.current===null?null:R0.current/sc;
  if(cur!==null && cur>=x0 && cur<=x1) s+=`<line x1="${X(cur)}" x2="${X(cur)}" y1="${mt}" y2="${mt+ph}" class="lim"/><text x="${X(cur)+4}" y="${mt+10}" class="halo" style="font-size:10px">${L('当前','now')}</text>`;
  let seg=[]; const flush=()=>{ if(seg.length>1) s+=`<polyline points="${seg.join(' ')}" class="swl"/>`; seg=[]; };
  P.forEach(p=>{ if(p.y===null||p.y===undefined) flush(); else seg.push(`${X(p.x)},${Y(p.y)}`); }); flush();
  P.forEach((p,i)=>{ if(!p.ok) s+=`<path d="M${X(p.x)-4} ${mt+ph-8}l8 8m0 -8l-8 8" class="swx" data-pt="${i}"><title>${esc(p.err||'')}</title></path>`;
    else if(p.y!==null&&p.y!==undefined) s+=`<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4" class="swp ${p.band?'':'out'}" data-pt="${i}"><title>${numv(p.x)} ${esc(R0.unit)} → ${f(p.y,m.digits)} ${m.unit}</title></circle>`; });
  return s+'</svg>';
}
function sweepPage(){
  const c=swCtl(), E=swEnds(), M=S.spec.metrics; const busy=!!S.jobs.sweep; const R0=S.sweep;
  const by={}; S.spec.controls.filter(x=>S.spec.sweepable.includes(x.path)).forEach(x=>{ (by[x.group]=by[x.group]||[]).push(x); });
  const opts=S.spec.groups.filter(g=>by[g.id]).map(g=>`<optgroup label="${esc(L(g.zh,g.en))}">${by[g.id].map(x=>`<option value="${x.path}" ${x.path===S.sw.path?'selected':''}>${esc(L(x.zh,x.en))}${x.unit?` [${esc(x.unit)}]`:''}</option>`).join('')}</optgroup>`).join('');
  const mopts=Object.keys(M).map(k=>`<option value="${k}" ${k===S.sw.metric?'selected':''}>${esc(L(M[k].zh,M[k].en))}${M[k].unit?` [${M[k].unit}]`:''}</option>`).join('');
  const form=`<div class="swform">
     <label>${L('扫哪个参数','Step which control')}<select data-sw="path" aria-label="sweep control">${opts}</select></label>
     <label>${L('从','From')}${c.unit?` [${esc(c.unit)}]`:''}<input data-sw="lo" inputmode="decimal" value="${numv(E.lo).replace('−','-')}" aria-label="sweep from"></label>
     <label>${L('到','To')}${c.unit?` [${esc(c.unit)}]`:''}<input data-sw="hi" inputmode="decimal" value="${numv(E.hi).replace('−','-')}" aria-label="sweep to"></label>
     <label>${L('点数','Points')} (2–${S.spec.sweep_max_points})<input data-sw="points" inputmode="numeric" value="${S.sw.points}" aria-label="sweep points"></label>
     <label>${L('看哪个数','Read which number')}<select data-sw="metric" aria-label="sweep metric">${mopts}</select></label>
     <div class="job" id="kjob-sweep">${busy?kjobHtml('sweep'):`<button class="btn pri" data-act="sweeprun" ${S.error||!S.run?'disabled':''}>▶ ${L('运行扫描','Run the sweep')}</button>${S.kmsg.sweep?`<div class="jobtxt"><span>${esc(S.kmsg.sweep)}</span></div>`:''}`}</div>
    </div>`;
  let res=`<div class="empty">${L('其余参数都取当前值,只动这一个;每个点是那份配置自己的统计引擎报告。配置层不收的值在图上是 ×,带它的原话。','Everything else stays as it is; each point is that config\'s own statistical report. A value the config refuses is a × with the schema\'s sentence.')}</div>`;
  if(R0){
    const m=M[S.sw.metric]; const sc=R0.scale; const snr=S.sw.metric!=='snr_cell_db';
    const val=p=>{ const v=p.metrics[S.sw.metric]; return typeof v==='boolean' ? (v?'✓':'✕') : f(v,m.digits); };
    const rows=R0.points.map((p,i)=>p.ok?`<tr><td class="n">${numv(p.x/sc)}</td><td class="n">${val(p)}</td>${snr?`<td class="n">${f(p.metrics.snr_cell_db,2)}</td>`:''}<td>${p.metrics.compliant===null?'—':p.metrics.compliant?'✓':'✕'}</td><td>${p.in_if_band?'✓':`<span class="pill warn" style="font-size:11px">${L('IF 带外','outside the IF band')}</span>`}</td><td><button class="btn sm" data-act="usepoint" data-pt="${i}">${L('用这个值','Use this value')}</button></td></tr>`
      :`<tr class="dim"><td class="n">${numv(p.x/sc)}</td><td colspan="${snr?5:4}"><span class="pill bad" style="font-size:11px">${L('配置层不接受','refused')}</span> ${esc(p.error)}</td></tr>`).join('');
    res=`<div class="chart" data-chart="sweep"></div>
     <div class="legend"><span><span class="swdot"></span>${L('一个点 = 一份报告','a point = a report')}</span><span><span class="swdot out"></span>${L('目标在 IF 带外','target outside the IF band')}</span><span>× ${L('配置层不接受的值','a value the config refuses')}</span><span><span class="sw-line" style="border-color:var(--ink);border-top-style:dashed"></span>${L('当前值','the current value')}</span></div>
     <div class="tblwrap" style="margin-top:12px"><table class="tbl swtbl"><thead><tr><th class="n">${esc(L(R0.zh,R0.en))}${R0.unit?` [${esc(R0.unit)}]`:''}</th><th class="n">${esc(L(m.zh,m.en))}${m.unit?` [${m.unit}]`:''}</th>${snr?`<th class="n">${L('格点 SNR [dB]','cell SNR [dB]')}</th>`:''}<th>${L('合规','compliant')}</th><th>${L('IF 带内','in the IF band')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  return `<div class="sp-page">${S.error?refusalBar():''}
   <div class="card"><div class="hdr"><div><h2>${L('扫描一个参数','Sweep one control')} ${R0&&stale(R0.config_sha256)?stalePill():''}</h2>
    <p class="sub">${L('把一个数值控件从一头拨到另一头,看一个结论数怎么跟着变。','Step one numeric control from one end to the other and watch one headline number follow.')}${R0?` <span class="num">${R0.points.length} ${L('点','points')} · ${R0.wall_s} s</span>`:''}</p></div></div>
    ${form}</div>
   <div class="card">${res}</div>
  </div>`;
}

/* ---------- the pinned baseline (a card on the workbench) ---------- */
function baselineCard(){
  if(!S.baseline) return `<div class="card span2 basebar" data-tab="results"><div class="baserow"><span class="sub" style="margin:0">${L('把当前这一组参数钉成基线,之后每次改动都对着它比:哪些控件变了、每个结论数朝哪边动。','Pin the current settings as a baseline; every later change is compared against it: which controls differ, and which way each headline number moved.')}</span><button class="btn sm" data-act="pin" ${S.run&&S.run.preview?'disabled':''}>${L('设为基线','Pin as baseline')}</button></div></div>`;
  const b=S.run.baseline; const M=S.spec.metrics;
  const head=`<div class="baserow"><b>${L('相对基线','Against the baseline')} <span class="mono" style="font-weight:400;color:var(--muted)">${S.baseline.sha.slice(0,10)}</span></b><span class="spacer"></span><button class="btn sm" data-act="pin" ${S.run&&S.run.preview?'disabled':''}>${L('把当前设为基线','Pin the current run')}</button><button class="btn sm" data-act="unpin">${L('清除基线','Clear')}</button></div>`;
  if(!b) return `<div class="card span2 basebar" data-tab="results">${head}</div>`;
  const cv=(c,v)=>v===null||v===undefined?L('留空','empty'):typeof v==='boolean'?String(v):`${numv(disp(c,v))}${c&&c.unit?' '+esc(c.unit):''}`;
  const ch=b.changed.map(x=>{ const c=S.spec.controls.find(k=>k.path===x.path); return `<span class="chg1">${esc(c?L(c.zh,c.en):x.path)} <span class="num">${cv(c,x.a)} → ${cv(c,x.b)}</span></span>`; }).join('');
  const mv=(k,v)=>typeof v==='boolean' ? (v?'✓':'✕') : f(v,M[k].digits);
  const moved=Object.keys(b.metrics).filter(k=>b.metrics[k].delta!==null && b.metrics[k].delta!==0);
  const rows=moved.map(k=>{ const r=b.metrics[k], m=M[k]; const cls=r.verdict==='better'?'ok':r.verdict==='worse'?'bad':'neu';
    return `<tr data-metric="${k}"><td>${esc(L(m.zh,m.en))}</td><td class="n">${mv(k,r.base)}</td><td class="n">${mv(k,r.now)}</td><td class="n">${typeof r.now==='boolean'?'':fs(r.delta,m.digits)} ${m.unit}</td><td><span class="pill ${cls}" data-verdict="${r.verdict}">${r.verdict==='better'?L('▲ 变好','▲ better'):r.verdict==='worse'?L('▼ 变差','▼ worse'):L('变了','moved')}</span></td></tr>`; }).join('');
  return `<div class="card span2 basebar" data-tab="results">${head}
   <div class="basechg">${b.changed.length?`<i>${L('改了','Changed')} ${b.changed.length}</i>${ch}`:`<i>${L('参数与基线相同','Same settings as the baseline')}</i>`}</div>
   ${moved.length?`<div class="tblwrap"><table class="tbl cmp basetbl"><thead><tr><th>${L('结论数','Number')}</th><th class="n">${L('基线','Baseline')}</th><th class="n">${L('现在','Now')}</th><th class="n">Δ</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:''}
   <p class="sub" style="margin:8px 0 0">${L(`其余 ${Object.keys(b.metrics).length-moved.length} 个结论数没有变。`,`The other ${Object.keys(b.metrics).length-moved.length} headline numbers did not move.`)}</p></div>`;
}
