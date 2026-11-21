/* fmcw_radar workbench.  The page draws and never computes: labels, units, ranges, defaults, tags, which control is
   idle and why, and every number shown come from Python (guispec / guiutil through the host's Api).  What the page
   does itself: unit display (value / scale), layout, and drawing the plot data it is handed. */
'use strict';
const S = {lang:'zh', theme:'auto', spec:null, sources:{}, values:{}, tags:{}, inert:{}, refused:{}, resolved:{}, run:null, frame:null,
           error:null, pending:false, dirty:false, job:null, jobMsg:null, lastWall:null, mtab:'results', open:{}};
Object.assign(S, {page:'workbench', sys:null, band:'current', sw:{path:'target.range_m', lo:null, hi:null, points:9, metric:'snr_cell_db'}, jobs:{sweep:null, bands:null}, kmsg:{}, baseline:null, bands:null, sweep:null, bandsFor:null, bandsShown:null, finalSeq:0, finalizing:false, finalBody:null, yamlMsg:null, yamlPanel:null, bundled:[]});
try{ const s = JSON.parse(localStorage.getItem('fmcw-ui')||'{}'); if(s.lang) S.lang=s.lang; if(s.theme) S.theme=s.theme; }catch(e){}
function save(){ try{ localStorage.setItem('fmcw-ui', JSON.stringify({lang:S.lang, theme:S.theme})); }catch(e){} }
const L = (zh,en) => S.lang==='zh' ? zh : en;
let RUN = null;                       // the current run in the shape the drawing code reads
const R = () => RUN;

/* ---------- transport: a host bridge when one is injected (Android), HTTP otherwise ---------- */
// On the phone the activity's bridge is asynchronous: host.call(id, route, json) returns at once and the reply
// comes back through window.onHostReply(id, text) -- Python runs on a thread of its own, the page stays alive.
const ON_DEVICE = !!(window.host && window.host.call);
let hostSeq=0; const pendingHost={};
window.onHostReply = (id, text) => { const done=pendingHost[id]; delete pendingHost[id]; if(done) done(text); };
async function api(route, body){
  if(ON_DEVICE){ const text = await new Promise(res=>{ const id=String(++hostSeq); pendingHost[id]=res; window.host.call(id, route, JSON.stringify(body===undefined?{}:body)); }); return JSON.parse(text); }
  const r = await fetch('api/'+route, body===undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  return r.json();
}

/* ---------- formatting ---------- */
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function f(x,d=2){ if(x===null||x===undefined) return '—'; const s=Math.abs(x).toFixed(d); return (x<0 && +s!==0 ? '−' : '') + s; }
function fs(x,d=2){ const s=Math.abs(x).toFixed(d); return (x<0 && +s!==0 ? '−' : '+') + s; }
function fe(x){ if(x===0) return '0'; const e=Math.floor(Math.log10(Math.abs(x))); const m=x/Math.pow(10,e); return (Math.abs(m-1)<1e-9?'':(m.toFixed(2)+'×'))+'10<sup>'+(e<0?'−':'')+Math.abs(e)+'</sup>'; }

function nice(x){ const e=Math.pow(10,Math.floor(Math.log10(x))); const m=x/e; return (m<1.5?1:m<3.5?2:m<7.5?5:10)*e; }
function tag(src, key, extra){ return `<button class="tag t-${src} ${extra&&extra!=='legend'?'edited':''}" data-src="${src}" data-key="${key||''}" data-extra="${esc(extra||'')}" aria-label="${src}">${src}</button>`; }
function edited(path){ const v=S.values[path], r=S.resolved[path]; return v!==null && v!==undefined && !!r && Number(v)!==Number(r.value); }
function T(path){ const t=S.tags[path]; if(!t) return ''; return tag(t, (S.resolved[path]||{}).key||'', edited(path)?path:''); }

/* ---------- the run, in the drawing code's shape ---------- */
function adapt(run, frame){
  const rep=run.report;
  const r={radar:rep.radar, target:rep.target, inputs:rep.inputs, budget:rep.budget, compliance:rep.compliance, detection:rep.detection,
    cfar:rep.cfar, nonlin:rep.nonlinearity||{}, pn:Object.assign({}, rep.phase_noise, {dither_bins:(rep.phase_noise.parked||{}).dither_bins}),
    chirp:rep.chirp||{}, full:run.full_power, plots:run.plots, repro:run.repro, engines:run.engines, wall:run.wall_s, warnings:run.warnings||[],
    pnc:Object.assign({}, run.plots.pn, {residual_l_dbc_hz_at_target:run.plots.pn.residual_l_dbc_hz})};
  if(frame){ const m=frame.rd_map;
    r.rd={rows:m.rows, cols:m.cols, rc:m.range_m_col_centres, vc:m.velocity_mps_row_centres, rspan:m.range_m_span, vspan:m.velocity_mps_span,
          floor:m.noise_floor_db_rel_peak, full:m.full_grid_shape, db:m.db_rel_peak};
    r.cells=frame.cells; r.counts=frame.cell_counts; r.time=frame.time_engine; r.frame=frame;
    r.frameStale = frame.config_sha256!==run.repro.config_sha256; }
  return r;
}

/* ---------- parameters: every control comes from the spec ---------- */
const disp = (c,v) => (v===null||v===undefined||typeof v!=='number'||c.scale===1) ? v : +(v/c.scale).toPrecision(7);
function shown(c){ const v=S.values[c.path]; if(v!==null && v!==undefined) return {v:disp(c,v), ph:false}; const r=S.resolved[c.path]; return r ? {v:disp(c,r.value), ph:true} : {v:'', ph:true}; }
function why(atoms){ return atoms.map(a=>{ const c=S.spec.controls.find(x=>x.path===a.path); const n=c?L(c.zh,c.en):a.path;
  return a.op==='in' ? `${n} = ${a.value.join(' / ')}` : a.op==='gt' ? `${n} > ${a.value}` : L(`${n} 已设置`,`${n} set`); }).join(L(',且 ',' and ')); }
function fieldRow(c){
  const cur=shown(c); const idle=S.inert[c.path]; const bad=S.error && S.error.field===c.path; let ctl;
  if(c.kind==='table'){ ctl=`<span class="num" style="font-size:12px">${(S.values[c.path]||[]).length} ${L('行','rows')}</span>`; }
  else if(c.kind==='bool' || c.choices){
    let opts = c.kind==='bool' ? [true,false] : c.choices; if(c.kind.startsWith('opt_') && !opts.includes(null)) opts=[null].concat(opts); const ref=S.refused[c.path]||[];
    ctl=`<select id="c-${c.path}" data-path="${c.path}" aria-label="${esc(c.en)}">${opts.map(o=>`<option value="${o===null?'':esc(String(o))}" ${String(S.values[c.path]??'')===String(o??'')?'selected':''} ${ref.includes(o)?'disabled':''}>${o===null?L('未设置','not set'):esc(String(o).split('/').pop())}</option>`).join('')}</select>`; }
  else { ctl=`<input id="c-${c.path}" inputmode="decimal" data-path="${c.path}" value="${esc(cur.v===null||cur.v===undefined?'':cur.v)}" class="${cur.ph?'ph':''} ${edited(c.path)?'chg':''}" ${c.lo!==null?`title="${c.lo} … ${c.hi} ${esc(c.unit)}"`:''} aria-label="${esc(c.en)}">`; }
  return `<div class="fld ${idle?'inert':''} ${bad?'bad':''}" data-fld="${c.path}"><label for="c-${c.path}">${L(c.zh,c.en)}<small>${c.path}</small></label><div class="fv">${ctl}<span class="u">${esc(c.unit)}</span><span class="tagslot">${T(c.path)}</span></div>${idle?`<div class="why">${L('此刻不起作用:需要 ','idle: needs ')}${esc(why(idle))}</div>`:''}</div>`;
}
function paramsPanel(){
  const cs=S.spec.controls; const groups=S.spec.groups;
  const html=groups.map(g=>{ const mine=cs.filter(c=>c.group===g.id); if(!mine.length) return ''; const top=mine.filter(c=>c.common), rest=mine.filter(c=>!c.common);
    const key='g-'+g.id; const isOpen = key in S.open ? S.open[key] : top.length>0;
    return `<details class="psec" data-key="${key}" ${isOpen?'open':''}><summary><span>${L(g.zh,g.en)} <i class="cnt">${mine.length}</i></span></summary>${top.map(fieldRow).join('')}${
      rest.length ? (top.length ? `<details class="rest" data-key="${key}-rest" ${S.open[key+'-rest']?'open':''}><summary>${L(`其余 ${rest.length} 项`,`${rest.length} more`)}</summary>${rest.map(fieldRow).join('')}</details>` : rest.map(fieldRow).join('')) : ''}</details>`; }).join('');
  const n=Object.keys(S.values).filter(p=>JSON.stringify(S.values[p])!==JSON.stringify(S.defaults[p])).length;
  return `<aside class="card params" data-tab="params">
   <div class="ph"><h2>${L('参数','Parameters')}</h2>${n?`<button class="btn sm" data-act="reset">${L(`恢复默认(已改 ${n} 项)`,`Defaults (${n} edited)`)}</button>`:''}</div>
   <div class="yamlrow"><button class="btn sm" data-act="yamlopen">${L('载入 YAML…','Load YAML…')}</button><button class="btn sm" data-act="yamlsave" ${S.error?'disabled':''}>${L('导出 YAML','Export YAML')}</button>${S.bundled.length?`<select data-yaml="bundled" aria-label="${L('随库配置','bundled configs')}"><option value="">${L('随库配置…','Bundled config…')}</option>${S.bundled.map(b=>`<option value="${b}">${b}</option>`).join('')}</select>`:''}<input type="file" id="yamlfile" accept=".yaml,.yml,text/yaml,text/plain" hidden></div>
   ${S.yamlMsg?`<p class="yamlmsg ${S.yamlMsg.ok?'':'bad'}">${esc(S.yamlMsg.text)}</p>`:''}
   ${S.yamlPanel?`<div class="yamlpanel"><p class="sub" style="margin:0 0 6px">${S.yamlPanel.mode==='out'?L(`${S.yamlPanel.name}:长按全选、复制。`,`${S.yamlPanel.name}: select all and copy.`):L('把配置文件的内容粘贴到这里。','Paste the config file\'s text here.')}</p><textarea id="yamltext" rows="8" spellcheck="false" ${S.yamlPanel.mode==='out'?'readonly':''} aria-label="YAML">${esc(S.yamlPanel.text)}</textarea><div class="yamlrow">${S.yamlPanel.mode==='in'?`<button class="btn sm pri" data-act="yamltake">${L('载入','Load')}</button>`:''}<button class="btn sm" data-act="yamlclose">${L('关闭','Close')}</button></div></div>`:''}
   <p class="sub" style="margin:0">${L(`${cs.length} 个字段,与配置一一对应;留空的字段显示库实际取的数和它的出处。`,`${cs.length} fields, one per config field; an empty field shows the number the library uses and its source.`)}</p>
   <div class="pgrid">${html}</div>
   <div class="psec"><div class="legend-tags">${Object.keys(S.spec.tags).map(k=>`<span>${tag(k,'','legend')} ${L(...S.spec.tags[k])}</span>`).join('')}</div></div>
  </aside>`;
}

/* ---------- KPIs ---------- */
function kpis(){
  const r=R(), c=r.compliance; const k=(lab,v,u,d,cls='')=>`<div class="kpi ${cls}"><div class="k">${lab}</div><div class="v">${v}<small>${u}</small></div><div class="d">${d}</div></div>`;
  const gpf=r.cfar.ghost_detections_per_frame||0; const gl=(r.cfar.ghosts||[]).map(g=>g.level_dbc); const strongest=gl.length?Math.max(...gl):null;
  let comp;
  if(!c.applies) comp=k(L('合规 · §15.255(c)(2)','Compliance · §15.255(c)(2)'), L('不适用','n/a'), '', L('扫频不在 57–71 GHz 内','sweep outside 57–71 GHz'));
  else { const gov=c.tiers.find(t=>t.tier===c.governing);
    const off = gov.off_time_have_s==null ? L('关断未判定','off-time not judged') : `${L('关断','off')} ${f(gov.off_time_have_s*1000,1)} / ≥ ${f(c.off_time_required_s*1000,1)} ms`;
    comp=k(L('合规 · §15.255(c)(2)','Compliance · §15.255(c)(2)'), c.compliant?L('通过','pass'):L('不合规','fail'), '', `EIRP ${f(c.eirp_dbm,1)} / ${f(c.limit_dbm,0)} dBm · ${L('裕度','margin')} ${fs(c.eirp_margin_db,1)} dB<br>${off}`, c.compliant?'ok':'bad'); }
  return `<div class="kpis span2" data-tab="results">${comp}
   ${k(L('格点 SNR','Cell SNR'), f(r.detection.snr_cell_db), 'dB', `Pd ${f(r.cfar.pd_target,2)} @ Pfa ${fe(r.cfar.pfa_design)}<br>${L(`Pd 0.9 需 ${f(r.cfar.snr_pd90_db)} dB`,`Pd 0.9 needs ${f(r.cfar.snr_pd90_db)} dB`)}`)}
   ${k(L('鬼目标 · 每帧期望检出','Ghosts · expected per frame')+(S.run.preview?` <span class="pill warn pv">${L('预览','preview')}</span>`:''), gpf<0.01&&gpf>0?gpf.toFixed(4):f(gpf,2), L('个',''), strongest===null?L('这个 chirp 引擎没有鬼目标清单','no ghost list from this chirp engine'):`${L('最强','strongest')} ${f(strongest,2)} dBc<br>${r.nonlin.ghosts_vouched?L('逐周期引擎背书','vouched by the cycle-accurate engine'):L('线性化引擎:不能背书','linearised engine: not vouched')}`, gpf>=0.5?'bad':'')}
   ${k(L('距离分辨率','Range res.'), f(r.radar.range_res_m*100,2), 'cm', `${r.radar.range_window} −3 dB<br>c/2B ${f(r.radar.range_res_rect_m*100,2)} cm`)}
   ${k(L('速度分辨率','Velocity res.'), f(r.radar.velocity_res_mps,3), 'm/s', L(`最大 ±${f(r.radar.max_velocity_mps,2)} m/s`,`max ±${f(r.radar.max_velocity_mps,2)} m/s`))}
   ${k(L('最大距离','Max range'), f(r.radar.max_range_m,2), 'm', L(`IF 带宽 ${r.radar.if_bw_mhz} MHz 限定`,`set by ${r.radar.if_bw_mhz} MHz IF`))}
  </div>`;
}

/* ---------- engines and the time-engine job ---------- */
function runbar(){
  const r=R(), E=S.spec.engines; const st=r.engines.find(e=>e.id==='statistical'), ch=r.engines.find(e=>e.id.startsWith('chirp:')); const t=r.time;
  const loc = t && t.snr_local_difference_db!=null; const d = t && (loc ? t.snr_local_difference_db : t.snr_difference_db);
  const eng=(id,cls,extra)=>`<div class="eng ${cls}"><b>${L(E[id].zh,E[id].en)} ${extra.badge||''} <span class="num r1">${extra.time||''}</span></b><span class="r">${L(E[id].does_zh,E[id].does_en)} ${extra.line||''}</span><span class="r scope"><i>${L('结论适用','Covers')}</i>${L(E[id].covers_zh,E[id].covers_en)}</span></div>`;
  return `<div class="card span2" data-tab="results"><div class="runbar"><div class="engrow">
    ${eng('statistical','main',{time:`${st.wall_s} s`})}
    ${eng('time','',{time:t?`${r.frame.wall_s} s`:'', line: t ? `<span class="pill ${Math.abs(d)<1?'ok':'bad'}" style="font-size:11px">${L('差','diff')} ${fs(d,2)} dB</span> ${L('目标格点 SNR 实测','target cell SNR measured')} <span class="num">${f(loc?t.snr_cell_local_db:t.snr_cell_db)}</span> / ${L('统计期望','expected')} <span class="num">${f(loc?t.snr_cell_local_expected_db:t.snr_cell_expected_db)} dB</span>${r.frameStale?` <span class="pill warn" style="font-size:11px">${L('属于上一组参数','from other settings')}</span>`:''}` : `<span class="pill neu" style="font-size:11px">${L('这组参数还没跑','not run for these settings')}</span>`})}
    ${eng(ch.id,'',{badge: ch.vouches_for_spurs?`<span class="pill ok" style="font-size:11px">${L('可为杂散背书','vouches for spurs')}</span>`:`<span class="pill warn" style="font-size:11px">${L('不能背书杂散','cannot vouch for spurs')}</span>`, line: ch.rms_hz!=null?`${L('频率误差','freq. error')} RMS <span class="num">${f(ch.rms_hz/1e6,3)} MHz</span>`:''})}
   </div><div class="job" id="jobslot">${jobHtml()}</div></div></div>`;
}
function jobHtml(){
  const j=S.job;
  if(j && (j.status==='queued'||j.status==='running')){ const el=j.elapsed_s||0; const eta=j.eta_s;
    return `<div class="jobtxt"><span>${j.status==='queued'?L('时域引擎排队中','Time engine queued'):L('时域引擎运行中','Time engine running')}</span><span class="num">${f(el,1)} s${eta?` / ≈${f(eta,1)} s`:''}</span></div>
     <div class="bar"><i style="width:${eta?Math.min(100,100*el/eta).toFixed(1):((el*8)%100).toFixed(1)}%"></i></div>
     <div class="jobtxt"><span>${eta?L('按上次实测耗时估计(库不报帧内进度)','estimated from the last measured run (no progress inside a frame)'):L('第一次运行,没有耗时可估','first run: nothing to estimate from')}</span><button class="btn sm" data-act="cancel">${L('取消','Cancel')}</button></div>`; }
  return `<button class="btn pri" data-act="frame" ${S.error?'disabled':''}>▶ ${L('运行时域引擎','Run time engine')}${S.lastWall?` <span class="num" style="opacity:.8">≈${f(S.lastWall,1)} s</span>`:''}</button>
   <div class="jobtxt"><span>${S.jobMsg||L('真波形 → 真混频 → 真 FFT;只做一致性检查,可取消。','real waveform → mixing → FFT; a consistency check, cancellable.')}</span></div>`;
}

/* ---------- R-D map ---------- */
function rdSvg(w){
  const r=R(), rd=r.rd; const compact=w<560;
  const ml=compact?34:44, mr=compact?8:14, mt=compact?20:22, mb=32;
  const pw=w-ml-mr, ph=compact?Math.round(pw*0.62):Math.min(360,Math.round(pw*0.42));
  const H=ph+mt+mb;
  const r0=rd.rspan[0], r1=rd.rspan[1];
  const c0=rd.rc[0], dc=(rd.rc[rd.cols-1]-c0)/(rd.cols-1);
  const v0=rd.vc[0], dv=(rd.vc[rd.rows-1]-v0)/(rd.rows-1);
  const X=m=>ml+(((m-c0)/dc)+0.5)/rd.cols*pw;
  const Y=v=>mt+((rd.rows-0.5)-((v-v0)/dv))/rd.rows*ph;
  let cells='';
  for(let i=0;i<rd.rows;i++){ const row=rd.db[i]; const y=rd.rows-1-i;
    for(let j=0;j<rd.cols;j++){ const o=Math.max(0,Math.min(1,(row[j]+50)/50)); if(o<0.02) continue; cells+=`<rect x="${j}" y="${y}" width="1.04" height="1.04" fill-opacity="${o.toFixed(2)}"/>`; } }
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="range-Doppler map">`;
  s+=`<rect x="${ml}" y="${mt}" width="${pw}" height="${ph}" class="heatbg"/>`;
  s+=`<svg x="${ml}" y="${mt}" width="${pw}" height="${ph}" viewBox="0 0 ${rd.cols} ${rd.rows}" preserveAspectRatio="none" shape-rendering="crispEdges"><g class="heat">${cells}</g></svg>`;
  // IF band
  const xm=X(r.radar.max_range_m);
  s+=`<rect x="${xm}" y="${mt}" width="${ml+pw-xm}" height="${ph}" class="oob"/>`;
  s+=`<line x1="${xm}" x2="${xm}" y1="${mt-4}" y2="${mt+ph}" class="lim"/><text x="${xm+4}" y="${mt-6}" class="halo">${L('IF 带外','beyond IF band')} ›</text><text x="${xm-4}" y="${mt-6}" text-anchor="end" class="halo num">${f(r.radar.max_range_m,2)} m</text>`;
  // axes
  const rs=nice((r1-r0)/(compact?5:9)); for(let m=Math.ceil(r0/rs-1e-9)*rs;m<=r1+1e-9;m+=rs){ const x=ml+(m-r0)/(r1-r0)*pw; s+=`<line x1="${x}" x2="${x}" y1="${mt+ph}" y2="${mt+ph+4}" class="tick"/><text x="${x}" y="${mt+ph+15}" text-anchor="middle">${+m.toFixed(2)}</text>`; }
  s+=`<text x="${ml+pw}" y="${H-3}" text-anchor="end">${L('距离 [m]','range [m]')}</text>`;
  const vs=nice((rd.vspan[1]-rd.vspan[0])/5); for(let v=Math.ceil(rd.vspan[0]/vs-1e-9)*vs;v<=rd.vspan[1]+1e-9;v+=vs){ const y=Y(v); s+=`<line x1="${ml-4}" x2="${ml}" y1="${y}" y2="${y}" class="tick"/><text x="${ml-6}" y="${y+3.5}" text-anchor="end">${f(v,vs<1?1:0)}</text>`; }
  s+=`<text x="4" y="${mt-8}">${L('速度 [m/s]','v [m/s]')}</text>`;
  s+=`<rect x="${ml}" y="${mt}" width="${pw}" height="${ph}" fill="none" class="axis"/>`;
  // markers
  const cl=r.cells;
  const tv=r.time.peak_velocity_mps;
  for(const c of cl.filter(c=>c.kind==='elsewhere')){ const x=X(c.range_m), y=Y(c.velocity_mps); s+=`<path d="M${x-3} ${y-3}L${x+3} ${y+3}M${x+3} ${y-3}L${x-3} ${y+3}" class="mm"><title>${f(c.range_m,2)} m, ${f(c.velocity_mps,2)} m/s</title></path>`; }
  for(const c of cl.filter(c=>c.kind==='target_doppler_row')){ s+=`<circle cx="${X(c.range_m)}" cy="${Y(c.velocity_mps)}" r="3" class="mm"/>`; }
  // expected ghosts
  r.cfar.ghosts.forEach((g,i)=>{ if(!(g.in_view && g.range_m>0 && g.range_m<r1)) return; const x=X(g.range_m), y=Y(tv); const d=compact?7:8;
    s+=`<path d="M${x} ${y-d}L${x+d} ${y}L${x} ${y+d}L${x-d} ${y}Z" class="ghx"><title>G${i+1}: ${f(g.range_m,2)} m, ${f(g.level_dbc,1)} dBc, Pd ${g.pd.toPrecision(2)}</title></path>`;
    s+=`<text x="${x}" y="${y+d+12}" text-anchor="middle" class="lg halo" style="font-size:10.5px">G${i+1} · Pd ${g.pd<0.01?g.pd.toExponential(1):g.pd.toFixed(2)}</text>`; });
  // detected ghosts grouped
  const grp={}; cl.filter(c=>c.kind==='ghost').forEach(c=>{(grp[c.ghost_index]=grp[c.ghost_index]||[]).push(c)});
  for(const k in grp){ const a=grp[k]; const x=a.reduce((s,c)=>s+X(c.range_m),0)/a.length, y=a.reduce((s,c)=>s+Y(c.velocity_mps),0)/a.length; const d=compact?5:5.5;
    s+=`<path d="M${x} ${y-d}L${x+d} ${y}L${x} ${y+d}L${x-d} ${y}Z" class="gh"><title>${L('鬼目标检出','ghost detected')} G${+k+1}: ${a.length} ${L('格','cells')}</title></path>`;
    s+=`<text x="${x}" y="${y-d-14}" text-anchor="middle" class="lg halo" style="font-size:10.5px">×${a.length}</text>`; }
  // target box
  const tl=cl.filter(c=>c.kind==='target_lobe'||c.kind==='other_target_lobe');
  if(tl.length){ const xs=tl.map(c=>X(c.range_m)), ys=tl.map(c=>Y(c.velocity_mps)); const p=6;
    const x0=Math.min(...xs)-p, x1=Math.max(...xs)+p, y0=Math.min(...ys)-p, y1=Math.max(...ys)+p;
    s+=`<rect x="${x0}" y="${y0}" width="${x1-x0}" height="${y1-y0}" rx="4" class="tgt"/>`;
    const lab=`${L('目标','target')} ${f(r.time.peak_range_m,2)} m · ${f(r.time.peak_velocity_mps,2)} m/s`;
    s+=`<text x="${x0}" y="${y0-16}" class="lt halo">${lab}</text>`; }
  // colour scale
  s+='</svg>';
  return s;
}

function rdCard(){
  const r=R(); const mk=(shape)=>`<svg viewBox="0 0 14 14">${shape}</svg>`;
  if(!r.rd) return `<div class="card span2" data-tab="results"><h2>${L('距离-多普勒图','Range-Doppler map')}</h2><div class="empty">${L('这张图来自时域引擎的一帧。统计引擎的结论(上面的数、下面的预算)不依赖它;要看图,运行时域引擎。','This map is one frame of the time engine. The statistical conclusions (the numbers above, the budget below) do not depend on it; run the time engine to see it.')}</div>${ghostList(r)}</div>`;
  const cnt=r.counts; const inview=(r.cfar.ghosts||[]).filter(g=>g.in_view && g.range_m>0);
  return `<div class="card span2 ${r.frameStale?'stalecard':''}" data-tab="results">
   <div class="hdr"><div><h2>${L('距离-多普勒图','Range-Doppler map')} ${r.frameStale?`<span class="pill warn">${L('上一组参数的帧','frame of other settings')}</span>`:''}</h2>
   <p class="sub">${L(`时域引擎这一帧(seed ${r.frame.seed})· ${r.rd.full[0]}×${r.rd.full[1]} 格降采样到 ${r.rd.rows}×${r.rd.cols}(每块取最大)· 颜色 = 相对图峰 dB,噪底 ${f(r.rd.floor,1)} dB`,`Time-engine frame (seed ${r.frame.seed}) · ${r.rd.full[0]}×${r.rd.full[1]} cells pooled to ${r.rd.rows}×${r.rd.cols} (block max) · colour = dB rel. peak, floor ${f(r.rd.floor,1)} dB`)}</p></div></div>
   <div class="chart ${r.frameStale?'dim':''}" data-chart="rd"></div>
   <div class="legend">
    <span>${mk('<rect x="2" y="3" width="10" height="8" rx="2" class="tgt"/>')}<b style="color:var(--target)">${L('真目标','true target')}</b> ${L(`主瓣内 ${cnt.target_lobe+cnt.other_target_lobe} 格过门限`,`${cnt.target_lobe+cnt.other_target_lobe} cells in the lobes`)}</span>
    <span>${mk('<path d="M7 1.5 12.5 7 7 12.5 1.5 7Z" class="gh"/>')}<b style="color:var(--ghost)">${L('鬼目标检出','ghost detected')}</b> ${cnt.ghost} ${L('格','cells')}</span>
    <span>${mk('<path d="M7 1.5 12.5 7 7 12.5 1.5 7Z" class="ghx"/>')}${L(`鬼目标期望位置(视野内 ${inview.length} 个)`,`expected ghost sites (${inview.length} in view)`)}</span>
    <span>${mk('<circle cx="7" cy="7" r="3" class="mm"/>')}${L(`目标多普勒行 ${cnt.target_doppler_row}`,`target Doppler row ${cnt.target_doppler_row}`)}</span>
    <span>${mk('<path d="M3.5 3.5 10.5 10.5M10.5 3.5 3.5 10.5" class="mm"/>')}${L(`其它 ${cnt.elsewhere}(期望噪声虚警 ${f(r.cfar.false_alarm_cells_per_frame,2)} 格/帧)`,`elsewhere ${cnt.elsewhere} (expected noise FA ${f(r.cfar.false_alarm_cells_per_frame,2)} cells/frame)`)}</span>
    ${cnt.leakage?`<span>${L(`泄漏附近 ${cnt.leakage} 格(未画)`,`${cnt.leakage} cells at the leakage (not drawn)`)}</span>`:''}
   </div>${ghostList(r)}
   <p class="sub" style="margin-top:6px">${L('格的分类是按位置贴的标签(规则见 guiutil.classify_cells),库只给过门限的格点。','Cell classes are positional labels (rule: guiutil.classify_cells); the library only lists threshold crossings.')}</p></div>`;
}
function ghostList(r){
  const g=r.cfar.ghosts||[]; if(!g.length) return '';
  const per = i => r.cells ? r.cells.filter(c=>c.kind==='ghost' && c.ghost_index===i).length : null;
  const mk=(shape)=>`<svg viewBox="0 0 14 14">${shape}</svg>`;
  const rows=[`<tr class="key"><td>${mk('<rect x="2" y="3" width="10" height="8" rx="2" class="tgt"/>')} ${L('真目标','true target')}</td><td class="n">${f(r.time?r.time.peak_range_interp_m:r.target.range_m,2)}</td><td class="n">${f(0,1)}</td><td class="n">${f(-r.cfar.snr_look_db,1)}</td><td class="n">${f(r.cfar.snr_look_db,1)}</td><td class="n">${f(r.cfar.pd_target,3)}</td><td class="n">${r.counts?r.counts.target_lobe:'—'}</td></tr>`]
   .concat(g.map((x,i)=>`<tr class="${x.in_view?'':'dim'}"><td>${mk(`<path d="M7 1.5 12.5 7 7 12.5 1.5 7Z" class="${per(i)?'gh':'ghx'}"/>`)} ${L('鬼目标','ghost')} G${i+1}${x.in_view?'':` <span class="oov">${L('图外','out of view')}</span>`}</td><td class="n">${f(x.range_m,2)}</td><td class="n"${x.level_map_dbc!==x.level_dbc?` title="${L('滤波前','ahead of the filter')} ${f(x.level_dbc,1)} dBc"`:''}>${f(x.level_map_dbc,1)}</td><td class="n">${f(x.floor_dbc,1)}</td><td class="n">${f(x.snr_db,1)}</td><td class="n">${x.pd<0.001?x.pd.toExponential(1):x.pd.toFixed(3)}</td><td class="n">${x.in_view && per(i)!==null?per(i):'—'}</td></tr>`)).join('');
  return `<h3>${L('检出清单','Detection list')}</h3><div class="tblwrap"><table class="tbl dlist"><thead><tr><th></th><th class="n">${L('距离 m','range m')}</th><th class="n">${g.some(x=>x.level_map_dbc!==x.level_dbc)?L('图上电平 dBc','level on the map dBc'):L('电平 dBc','level dBc')}</th><th class="n">${L('所在处噪底 dBc','floor there dBc')}</th><th class="n">SNR dB</th><th class="n">Pd</th><th class="n">${L('这一帧过门限格','cells this frame')}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

/* ---------- budget ---------- */
const BT = {'EIRP':'EIRP','free-space path loss (4pi)^3 R^4 / lambda^2':'自由空间路径损耗 (4π)³R⁴/λ²','oxygen over 2R':'氧气吸收(往返 2R)','extra two-way loss':'额外往返损耗','RCS':'RCS','received power P_r':'接收功率 P_r','signal at the ADC':'ADC 处信号','thermal noise density at the antenna k T0 F':'天线处热噪声密度 kT₀F','thermal noise density at the ADC':'ADC 处热噪声密度','ADC quantisation noise density':'ADC 量化噪声密度','total noise density at the ADC':'ADC 处总噪声密度','C/N0':'C/N₀','SNR, one chirp, one range bin':'SNR · 单 chirp 单距离格','SNR, one range-Doppler cell':'SNR · 单距离-多普勒格','SNR, rectangular windows (matched filter)':'SNR · 矩形窗(匹配滤波)','window loss':'窗损失','in-band P1dB margin (input, target only)':'带内 P1dB 裕量(输入,仅目标)',"IF high-pass at the target's beat (echo and thermal noise)":'IF 高通在目标拍频处的衰减(回波与热噪声同扣)'};
const KEYROWS = new Set(['EIRP','received power P_r','SNR, one range-Doppler cell']);

const BGROUP = {'EIRP':['发射与传播','Transmit and propagation'],'signal at the ADC':['接收与噪声','Receive and noise'],'SNR, one chirp, one range bin':['处理后的 SNR','SNR after processing'],'in-band P1dB margin (input, target only)':['余量','Margin']};

function budgetCard(){
  const r=R(), full=r.full, inp=r.inputs, c=r.compliance;
  const A = {
   'EIRP': `${f(inp.tx_power_dbm.value,1)} dBm ${T('frontend.tx_power_dbm')} − ${L('回退','backoff')} ${full?'<b>0</b> / ':''}<b>${f(inp.tx_backoff_db.value,1)}</b> dB ${T('frontend.tx_backoff_db')} + ${f(inp.tx_gain_dbi.value,1)} dBi ${T('frontend.tx_gain_dbi')}`,
   'free-space path loss (4pi)^3 R^4 / lambda^2': `R = ${f(inp.range_m.value,2)} m · λ = ${f(inp.wavelength_m.value*1000,3)} mm`,
   'oxygen over 2R': `${f(inp.oxygen_db_per_km.value,3)} dB/km ${T('channel.oxygen_db_per_km')}`,
   'RCS': `${esc(r.target.kind)} ${T('target.rcs_dbsm')}`,
   'received power P_r': `${L('接收天线','RX antenna')} ${f(inp.rx_gain_dbi.value,1)} dBi ${T('frontend.rx_gain_dbi')}`,
   'signal at the ADC': `${L('接收链增益','RX chain gain')} ${f(inp.rx_gain_db.value,1)} dB ${T('frontend.rx_gain_db')}`,
   'thermal noise density at the antenna k T0 F': `NF ${f(inp.nf_db.value,1)} dB ${T('frontend.nf_db')}`,
   'in-band P1dB margin (input, target only)': `P1dB ${f(inp.p1db_inband_dbm.value,1)} dBm ${T('frontend.p1db_inband_dbm')}`,
  };
  const ncol = full ? 4 : 2;
  const rows = r.budget.map((b,i)=>{ const a=full?full.budget.find(x=>x.term===b.term):null; const d=a?b.value-a.value:0; const isKey=KEYROWS.has(b.term);
    const g = BGROUP[b.term] ? `<tr class="grp"><td colspan="${ncol}">${L(...BGROUP[b.term])}</td></tr>` : '';
    return g+`<tr class="${isKey?'key':''} ${b.term==='SNR, one range-Doppler cell'?'hl':''}"><td class="term">${L(BT[b.term]||b.term,b.term)} <span class="bu">${b.unit}</span>${A[b.term]?`<div class="ann">${A[b.term]}</div>`:''}</td>${a?`<td class="n">${f(a.value)}</td>`:''}<td class="n">${f(b.value)}</td>${a?`<td class="n ${Math.abs(d)<1e-9?'':(d<0?'delta-neg':'delta-pos')}">${Math.abs(d)<1e-9?'·':fs(d,1)}</td>`:''}</tr>`; }).join('');
  const fc = full && full.compliance;
  return `<div class="card" data-tab="budget"><h2>${L('链路预算','Link budget')}</h2>
   <p class="sub">${L(`目标:${esc(r.target.kind)} ${r.target.range_m} m · ${r.target.velocity_mps} m/s;统计引擎。每个外部输入和它的出处标签写在用到它的那一行下面。`,`Target: ${esc(r.target.kind)} at ${r.target.range_m} m · ${r.target.velocity_mps} m/s; statistical engine. Each external input and its source tag sit under the row that uses it.`)}</p>
   <div class="tblwrap"><table class="tbl budget b2"><thead><tr><th>${L('项','Term')}</th>
    ${full?`<th class="n"><div class="colhead">${L('满功率','Full power')}<em style="color:${fc.applies&&!fc.compliant?'var(--bad)':'var(--muted)'}">${fc.applies?(fc.compliant?L('合规','compliant'):`${L('超限','over')} ${f(-fc.eirp_margin_db,1)} dB`):''}</em></div></th>`:''}
    <th class="n"><div class="colhead">${full?L('当前(已回退)','Now (backed off)'):L('当前','Now')}<em style="color:${c.applies?(c.compliant?'var(--ok)':'var(--bad)'):'var(--muted)'}">${c.applies?`${L('裕度','margin')} ${fs(c.eirp_margin_db,1)} dB`:''}</em></div></th>
    ${full?'<th class="n">Δ</th>':''}</tr></thead><tbody>${rows}</tbody></table></div>
   ${full?`<p class="sub" style="margin-top:8px">${L(`回退 ${f(inp.tx_backoff_db.value,1)} dB 的代价:格点 SNR ${f(full.snr_cell_db)} → ${f(r.detection.snr_cell_db)} dB;图上 Pd 0.9 要 ${f(r.cfar.snr_pd90_db)} dB。`,`Cost of the ${f(inp.tx_backoff_db.value,1)} dB backoff: cell SNR ${f(full.snr_cell_db)} → ${f(r.detection.snr_cell_db)} dB; Pd 0.9 on the map takes ${f(r.cfar.snr_pd90_db)} dB.`)}</p>`:''}</div>`;
}

/* ---------- compliance ---------- */
const TIERZH = {radar_default:'默认档:频段内任何场扰传感器 / 雷达', radar_57_59p4_indoor:'57.0–59.4 GHz,室内', radar_57_59p4_outdoor:'57.0–59.4 GHz,室外', radar_57_61p56:'57.0–61.56 GHz,无关断时间', radar_57_61p56_off_time:'57.0–61.56 GHz,带关断时间', radar_57_64:'57.0–64.0 GHz,带关断时间', radar_57_64_outdoor:'57.0–64.0 GHz,室外固定或车载,带关断时间', radar_61_61p5:'61.0–61.5 GHz,带宽 ≤ 500 MHz', radar_uav_60_64:'60–64 GHz,无人机上,带关断时间'};
const TIERSEC = {radar_default:'§15.255(c)(2)', radar_57_59p4_indoor:'(c)(2)(i)', radar_57_59p4_outdoor:'(c)(2)(i)', radar_57_61p56:'(c)(2)(ii)', radar_57_61p56_off_time:'(c)(2)(ii)', radar_57_64:'(c)(2)(iii)(A)', radar_57_64_outdoor:'(c)(2)(iii)(B)', radar_61_61p5:'(c)(2)(v)', radar_uav_60_64:'(b)(3)'};
const READZH = ['条文没定义"室内""室外""固定""车载":配置里的 regulatory.scenario 照字面采信。','占用带宽取指令扫频(中心 ± 扫频/2);条文没说怎么测,也没为 (f) 款的温度、电源范围留余量。','关断时间须连续至少 2 ms 才算;被 33 ms 区间截断的那一段,只算区间内的部分。','条文没说多个发射通道怎么相加。TDM:同一时刻只有一个发射机开,EIRP 取单个发射机的。','峰值 EIRP 取 tx_power_dbm − tx_backoff_db + tx_gain_dbi,峰值传导功率取 tx_power_dbm − tx_backoff_db;条文没给测量带宽。'];
function tierWhy(t){ if(t.usable) return L('可用','usable'); if(!t.in_band) return L('扫频不在档内','sweep not inside'); if(t.scenario==='not declared') return L('场景未声明','scenario not declared'); return L('不可用','not usable'); }

function offSvg(w){
  const c=R().compliance; const gov=c.tiers.find(t=>t.tier===c.governing);
  const win=33, on=c.frame_on_s*1000, have=gov.off_time_have_s*1000, req=c.off_time_required_s*1000;
  const ml=6, mr=6, pw=w-ml-mr, X=t=>ml+t/win*pw; const H=64;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}">`;
  s+=`<rect x="${X(0)}" y="14" width="${X(on)-X(0)}" height="18" rx="3" style="fill:var(--accent)"/>`;
  s+=`<rect x="${X(on)}" y="14" width="${X(win)-X(on)}" height="18" rx="3" style="fill:var(--ok-soft);stroke:var(--ok)"/>`;
  s+=`<text x="${X(0)}" y="10" class="lbl" style="font-size:10.5px">${L('发射','on')} ${f(on,1)} ms</text>`;
  s+=`<text x="${X(win)}" y="10" text-anchor="end" style="font-size:10.5px">${L('关断','off')} ${f(have,2)} ms</text>`;
  s+=`<line x1="${X(win-req)}" x2="${X(win-req)}" y1="10" y2="38" class="lim"/><text x="${X(win-req)}" y="50" text-anchor="middle" style="font-size:10.5px">${L('要求关断','required off')} ≥ ${f(req,1)} ms</text>`;
  s+=`<text x="${X(win)}" y="62" text-anchor="end" style="font-size:10px">33 ms</text><text x="${X(0)}" y="62" style="font-size:10px">0</text></svg>`;
  return s;
}
function tiersSvg(w, sweep, govId, tiers){
  const compact=w<520; const g0=56.5, g1=71.5; const ml=8, mr=compact?44:54; const pw=w-ml-mr; const X=g=>ml+(g-g0)/(g1-g0)*pw;
  const rh=compact?32:26; const top=18; const H=top+tiers.length*rh+20;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}">`;
  s+=`<rect x="${X(sweep[0])}" y="${top-6}" width="${X(sweep[1])-X(sweep[0])}" height="${tiers.length*rh+6}" style="fill:var(--accent-soft)"/>`;
  s+=`<text x="${(X(sweep[0])+X(sweep[1]))/2}" y="${top-8}" text-anchor="middle" class="lbl" style="font-size:10.5px;fill:var(--accent)">${L('扫频','sweep')} ${sweep[0]}–${sweep[1]}</text>`;
  [57,59,61,63,65,67,69,71].forEach(g=>{ s+=`<line x1="${X(g)}" x2="${X(g)}" y1="${top}" y2="${top+tiers.length*rh}" class="grid"/><text x="${X(g)}" y="${H-4}" text-anchor="middle" style="font-size:10px">${g}</text>`; });
  s+=`<text x="${w-2}" y="${H-4}" text-anchor="end" style="font-size:10px">GHz</text>`;
  tiers.forEach((t,i)=>{ const y=top+i*rh; const b=t.band_ghz; const gov=t.tier===govId; const usable=t.usable;
    const by=compact?y+15:y+5; const bh=compact?11:14;
    const st = gov ? 'fill:var(--ok);' : usable ? 'fill:var(--muted-mark);opacity:.6;' : 'fill:none;stroke:var(--line2);stroke-dasharray:3 2;';
    s+=`<rect x="${X(b[0])}" y="${by}" width="${Math.max(2,X(b[1])-X(b[0]))}" height="${bh}" rx="2" style="${st}"><title>${esc(t.label)}</title></rect>`;
    const lim=(t.peak_eirp_limit_dbm??t.limit_dbm);
    s+=`<text x="${w-2}" y="${by+bh-2}" text-anchor="end" class="num ${gov?'lbl':''}" style="font-size:11px">${lim} dBm</text>`;
    const lab = L(TIERZH[t.tier],t.label);
    if(compact){ s+=`<text x="${ml}" y="${y+11}" style="font-size:10.5px;${gov?'fill:var(--ink);font-weight:650':''}">${esc(lab)} · ${tierWhy(t)}</text>`; }
    else { const tx = X(b[1])+6; const right = tx < ml+pw*0.55; const left=!right && X(b[0])-6>ml+pw*0.45; s+=`<text x="${right?tx:(left?X(b[0])-6:X(b[0])+6)}" y="${by+11}" text-anchor="${left?'end':'start'}" class="halo" style="font-size:10.5px;${gov?'fill:var(--ink);font-weight:650':''}">${esc(lab)} · ${tierWhy(t)}</text>`; }
  });
  s+='</svg>'; return s;
}

function complianceCard(){
  const r=R(), c=r.compliance, inp=r.inputs;
  if(!c.applies) return `<div class="card" data-tab="budget"><h2>${L('合规检查','Compliance check')} <span class="pill neu">${L('不适用','not applicable')}</span></h2><p class="sub">${c.rule}</p><div class="note info">${esc(c.why)}</div></div>`;
  const gov=c.tiers.find(t=>t.tier===c.governing);
  return `<div class="card" data-tab="budget">
   <div class="hdr"><div><h2>${L('合规检查','Compliance check')} <span class="pill ${c.compliant?'ok':'bad'}">${c.compliant?'✓ '+L('合规','compliant'):'✕ '+L('不合规','not compliant')}</span></h2>
   <p class="sub">${c.rule} ${tag('spec','fcc15255.band_low_hz')} · ${esc(c.why)}</p></div></div>
   <div class="note ${c.compliant?'info':''}" style="margin-top:0">${esc(c.verdict)}</div>
   <div class="cgrid">
    <div class="cbox"><div class="k">${L('适用档(治理档)','Governing tier')}</div><div class="v" style="font-size:13px;font-family:var(--sans)">${L(TIERZH[c.governing]||gov.label,gov.label)}</div><div class="d">${TIERSEC[c.governing]||''} · ${L('能用的档里上限最高的','highest limit among usable tiers')}</div></div>
    <div class="cbox ${c.eirp_margin_db>=0?'good':'badv'}"><div class="k">${L('EIRP 裕度','EIRP margin')}</div><div class="v">${fs(c.eirp_margin_db,1)} dB</div><div class="d">${L('上限','limit')} ${f(c.limit_dbm,0)} dBm ${tag('spec','fcc15255.'+c.governing+'.peak_eirp_dbm')}</div>
     <div class="d eq">${f(c.tx_power_dbm,1)} dBm ${T('frontend.tx_power_dbm')} − ${f(c.tx_backoff_db,1)} dB ${T('frontend.tx_backoff_db')} + ${f(inp.tx_gain_dbi.value,1)} dBi ${T('frontend.tx_gain_dbi')} = <b>${f(c.eirp_dbm,1)} dBm</b></div></div>
    <div class="cbox ${gov.off_time==='met'||gov.off_time==='none required'?'good':'badv'}"><div class="k">${L('关断时间','Off-time')}</div><div class="v">${gov.off_time_have_s==null?'—':f(gov.off_time_have_s*1000,2)+' ms'}</div><div class="d">${c.off_time_required_s==null?L('这一档不要求','none required in this tier'):`${L('要求','need')} ≥ ${f(c.off_time_required_s*1000,1)} ms / 33 ms`} · ${esc(gov.off_time)}</div></div>
    <div class="cbox"><div class="k">${L('最高帧率','Max frame rate')}</div><div class="v">${c.max_frame_rate_hz==null?L('不限','no limit'):f(c.max_frame_rate_hz,2)+' /s'}</div><div class="d">${c.min_frame_period_s==null?'':`${L('最小帧周期','min frame period')} ${f(c.min_frame_period_s*1000,2)} ms · `}${L('配置','config')} ${c.frame_period_s==null?L('未声明','not declared'):f(c.frame_period_s*1000,2)+' ms'}</div></div>
   </div>
   ${gov.off_time_have_s!=null && c.off_time_required_s!=null ? `<h3>${L('一帧的发射时序(33 ms 区间)','Transmit timing in a 33 ms interval')}</h3><div class="chart" data-chart="offtime"></div>`:''}
   <h3>${L('九档限值与扫频','The nine tiers against the sweep')}</h3><div class="chart" data-chart="tiers"></div>
   <details class="more"><summary>${L('本库对条文的五条读法(条文没说的)','Five readings the rule leaves open')}</summary><ol>${c.readings.map((x,i)=>`<li>${L(READZH[i]||esc(x),esc(x))}</li>`).join('')}</ol></details></div>`;
}

/* ---------- phase noise and ghosts ---------- */
const LFC = [['lo','LO L(f)','var(--ink)',2.2,''],['res',null,'var(--accent)',2.2,''],['tdc_quant','tdc_quant','var(--c3)',1.3,'4 3'],['dco','dco','var(--c4)',1.3,'4 3'],['tdc_jitter','tdc_jitter','var(--c5)',1.3,'2 3'],['ref','ref','var(--c6)',1.3,'2 3'],['tdc_dither_mod','tdc_dither_mod','var(--c2)',1.3,'6 2']];
function lfLegend(on){ return LFC.filter(c=>c[0]!=='tdc_dither_mod'||on).map(c=>`<span><span class="sw-line" style="border-color:${c[2]};border-top-width:${c[3]>2?2.5:1.5}px;border-top-style:${c[4]?'dashed':'solid'}"></span>${c[1]||L('目标处残余','residual at target')}</span>`).join(''); }

function lfSvg(w){
  const pc=R().pnc; const ml=42, mr=10, mt=8, mb=30; const pw=w-ml-mr, ph=Math.min(240,Math.max(170,pw*0.5)); const H=ph+mt+mb;
  const lx0=4, lx1=Math.log10(pc.f_hz[pc.f_hz.length-1]); const all=pc.lo_l_dbc_hz.concat(pc.residual_l_dbc_hz_at_target); const y1=Math.ceil((Math.max(...all)+5)/20)*20, y0=y1-80;
  const X=fz=>ml+(Math.log10(fz)-lx0)/(lx1-lx0)*pw; const Y=v=>mt+(y1-Math.max(y0,Math.min(y1,v)))/(y1-y0)*ph;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="L(f)">`;
  for(let v=y0;v<=y1;v+=20){ s+=`<line x1="${ml}" x2="${ml+pw}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${ml-5}" y="${Y(v)+3.5}" text-anchor="end">${f(v,0)}</text>`; }
  [[1e4,'10k'],[1e5,'100k'],[1e6,'1M'],[1e7,'10M']].forEach(([fz,l])=>{ s+=`<line x1="${X(fz)}" x2="${X(fz)}" y1="${mt}" y2="${mt+ph}" class="grid"/><text x="${X(fz)}" y="${mt+ph+14}" text-anchor="middle">${l}</text>`; });
  s+=`<text x="${ml+pw}" y="${H-3}" text-anchor="end">${L('偏移 [Hz]','offset [Hz]')}</text><text x="2" y="${mt+10}" style="font-size:10px">dBc/Hz</text>`;
  const bw=R().radar.lo_loop_bw_mhz*1e6; s+=`<line x1="${X(bw)}" x2="${X(bw)}" y1="${mt}" y2="${mt+ph}" class="lim" style="opacity:.5"/><text x="${X(bw)+3}" y="${mt+ph-4}" style="font-size:10px">${L('环路带宽','loop BW')}</text>`;
  const path=(arr)=>arr.map((v,i)=>(i?'L':'M')+X(pc.f_hz[i]).toFixed(1)+' '+Y(v).toFixed(1)).join('');
  for(const c of LFC.slice().reverse()){ const arr = c[0]==='lo' ? pc.lo_l_dbc_hz : c[0]==='res' ? pc.residual_l_dbc_hz_at_target : pc.components_l_dbc_hz[c[0]];
    if(arr) s+=`<path d="${path(arr)}" fill="none" style="stroke:${c[2]};stroke-width:${c[3]}" stroke-dasharray="${c[4]}"/>`; }
  s+=`<text x="${X(1e6)+4}" y="${Y(pc.l_1mhz_dbc_hz)-6}" class="lbl halo" style="font-size:10.5px">${f(pc.l_1mhz_dbc_hz,2)} @1 MHz</text></svg>`;
  return s;
}
function ghostSvg(w){
  const g=R().plots.ghosts; const st=g.stems; if(!st.length) return '';
  const ml=40, mr=10, mt=10, mb=30; const pw=w-ml-mr, ph=190; const H=ph+mt+mb;
  const xm=Math.max(5,...st.map(x=>Math.abs(x.offset_m)))*1.12; const lo=Math.min(...st.map(x=>x.level_dbc), g.limit_dbc==null?0:g.limit_dbc);
  const y1=Math.ceil((Math.max(...st.map(x=>x.level_dbc))+6)/10)*10, y0=Math.floor((lo-4)/10)*10;
  const X=m=>ml+(m+xm)/(2*xm)*pw; const Y=v=>mt+(y1-v)/(y1-y0)*ph;
  let s=`<svg viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="ghosts">`;
  for(let v=y0;v<=y1;v+=10){ s+=`<line x1="${ml}" x2="${ml+pw}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${ml-5}" y="${Y(v)+3.5}" text-anchor="end">${f(v,0)}</text>`; }
  const xs=nice(2*xm/6); for(let m=Math.ceil(-xm/xs)*xs;m<=xm;m+=xs){ s+=`<text x="${X(m)}" y="${mt+ph+14}" text-anchor="middle">${f(m,xs<1?1:0)}</text>`; }
  s+=`<line x1="${X(0)}" x2="${X(0)}" y1="${mt}" y2="${mt+ph}" style="stroke:var(--target);stroke-width:1.5"/><text x="${X(0)+4}" y="${mt+10}" class="lt" style="font-size:10.5px">${L('目标','target')}</text>`;
  s+=`<text x="${ml+pw}" y="${H-3}" text-anchor="end">${L('相对目标 [m]','offset from target [m]')}</text><text x="2" y="${mt+8}" style="font-size:10px">dBc</text>`;
  if(g.limit_dbc!=null){ s+=`<line x1="${ml}" x2="${ml+pw}" y1="${Y(g.limit_dbc)}" y2="${Y(g.limit_dbc)}" style="stroke:var(--ink);stroke-dasharray:5 3"/><text x="${ml+pw-3}" y="${mt+10}" text-anchor="end" class="halo" style="font-size:10px">- - ${L('检出限','limit')} ${f(g.limit_dbc,1)} dBc</text>`; }
  st.forEach(x=>{ s+=`<line x1="${X(x.offset_m)}" x2="${X(x.offset_m)}" y1="${Y(y0)}" y2="${Y(x.level_dbc)}" style="stroke:var(--ghost);stroke-width:2"/><circle cx="${X(x.offset_m)}" cy="${Y(x.level_dbc)}" r="4" class="gh"><title>${f(x.offset_m,2)} m, ${f(x.level_dbc,2)} dBc</title></circle>`; });
  return s+'</svg>';
}
function pnCard(){
  const r=R(); const g=r.plots.ghosts; const lv=g.stems.map(x=>x.level_dbc); const pds=(r.cfar.ghosts||[]).map(x=>x.pd);
  const cd=S.spec.controls.find(c=>c.path==='lo.tdc_dither_lsb'); const dl=S.values['lo.tdc_dither_lsb']||0;
  const row=(lab,v)=>`<tr><td>${lab}</td><td class="n">${v}</td></tr>`; const hp=r.pn.floor.some(x=>x.map_shift_db);
  return `<div class="card span2" data-tab="pn">
   <div class="hdr"><div><h2>${L('相噪与鬼目标','Phase noise & ghosts')}</h2>
    <p class="sub">${L(`TX / RX 共用 LO,经往返延迟 τ = ${f(r.pnc.tau_s*1e9,2)} ns 相关抵消:LO 积分相位 ${f(r.pn.lo_rms_rad,4)} rad → 残余 ${f(r.pn.residual_rms_rad,4)} rad。`,`TX and RX share one LO; correlation over τ = ${f(r.pnc.tau_s*1e9,2)} ns: LO integrated phase ${f(r.pn.lo_rms_rad,4)} rad → residual ${f(r.pn.residual_rms_rad,4)} rad.`)}</p></div>
    <button class="toggle" data-act="dither" role="switch" aria-checked="${dl>0}"><span class="sw" aria-hidden="true" aria-checked="${dl>0}"></span><b>${L(cd.zh,cd.en)}</b> <span class="mono">${dl>0?`${dl} LSB`:L('关','off')}</span></button></div>
   <div class="pngrid">
    <div><h3 style="margin-top:0">${L('鬼目标:相对目标的距离偏移与电平','Ghosts: offset from target and level')}</h3>${lv.length?'<div class="chart" data-chart="ghosts"></div>':`<div class="empty">${L('这个 chirp 引擎下没有超过检出限的相干杂散(或引擎不给清单)。','No coherent spur above the detection limit under this chirp engine (or it gives no list).')}</div>`}
     ${g.vouched?'':`<div class="note">${L('当前 chirp 引擎不是逐周期引擎:这里的鬼目标结论不能背书(铁律 6)。','The chirp engine is not the cycle-accurate one: ghost conclusions here are not vouched for (invariant 6).')}</div>`}</div>
    <div><h3 style="margin-top:0">${L('这次运行','This run')}</h3><div class="tblwrap"><table class="tbl"><tbody>
      ${row(L('最强鬼目标','strongest ghost'), lv.length?f(Math.max(...lv),2)+' dBc':'—')}
      ${row(L('鬼目标检出限','ghost detection limit'), g.limit_dbc==null?'—':f(g.limit_dbc,2)+' dBc')}
      ${row(L('最强鬼目标的 Pd','Pd, likeliest ghost'), pds.length?(Math.max(...pds)<0.01?Math.max(...pds).toExponential(1):Math.max(...pds).toFixed(3)):'—')}
      ${row(L('每帧期望检出鬼目标','ghost detections / frame'), f(r.cfar.ghost_detections_per_frame||0,4))}
      ${row(L('TDC 输入处 dither','dither at the TDC input'), r.pn.dither_bins==null?'—':f(r.pn.dither_bins,2)+' bin')}
      ${row(L('LO 积分相位','LO integrated phase'), f(r.pn.lo_rms_rad,4)+' rad')}
      ${row(L('残余相位(目标处)','residual at the target'), f(r.pn.residual_rms_rad,4)+' rad')}
      ${row(L('峰值旁瓣','peak sidelobe'), r.nonlin.peak_sidelobe_db==null?'—':f(r.nonlin.peak_sidelobe_db,2)+' dB')}
      ${row('ISLR', r.nonlin.islr_db==null?'—':f(r.nonlin.islr_db,2)+' dB')}
      ${row(L('chirp 频率误差 RMS','chirp freq. error RMS'), r.chirp.rms_hz==null?'—':f(r.chirp.rms_hz/1e6,3)+' MHz')}
     </tbody></table></div></div>
    <div><h3>${L('L(f):LO 与目标处残余','L(f): the LO and its residual at the target')}</h3><div class="chart" data-chart="lf"></div><div class="legend">${lfLegend(dl>0)}</div></div>
    <div><h3>${L('目标旁的相噪底','Phase-noise floor beside the target')}</h3>
     <div class="tblwrap"><table class="tbl"><thead><tr><th>${L('离目标','offset')}</th><th class="n">${L('每距离格','per range bin')}</th><th class="n">${L('每距离-多普勒格','per R-D cell')}</th>${hp?`<th class="n">${L('图上(过高通后)','on the map (behind the high-pass)')}</th>`:''}</tr></thead><tbody>
     ${r.pn.floor.map(x=>`<tr><td class="num">${x.offset_m} m</td><td class="n">${f(x.per_bin_dbc,2)} dBc</td><td class="n">${f(x.per_cell_dbc,2)} dBc</td>${hp?`<td class="n">${f(x.per_cell_map_dbc,2)} dBc</td>`:''}</tr>`).join('')}</tbody></table></div>
     ${hp?`<p class="sub">${L('dBc 是滤波前拍频信号里的相对电平;图上旁瓣和目标各自在自己的拍频处过高通,比目标远的抬高、近的压低。鬼目标图同理,图上的值见距离-多普勒页的检出清单。','Levels in dBc are the beat signal’s ahead of the filter; on the map a sideband and the target each pass the high-pass at their own beat, so what lies farther out than the target stands higher and what lies nearer lower. The same holds for the ghost plot; the detection list on the range-Doppler page has the levels on the map.')}</p>`:''}
     ${r.warnings.length?`<div class="note"><b>${L('库的提示(原话)','Notes from the library (verbatim)')}</b>${r.warnings.map(x=>`<details class="orig"><summary>${esc(x.slice(0,90))}…</summary>${esc(x)}</details>`).join('')}</div>`:''}</div>
   </div></div>`;
}

/* ---------- consistency, reproducibility ---------- */
function timeCard(){
  const r=R(), t=r.time; if(!t) return '';
  return `<div class="card ${r.frameStale?'dim':''}" data-tab="results"><h2>${L('一致性:时域 vs 统计','Consistency: time vs statistical')}</h2>
   <p class="sub">${L('时域引擎不出结论,只核对统计引擎。','The time engine draws no conclusions; it checks the statistical one.')}</p>
   <table class="tbl"><thead><tr><th></th><th class="n">${L('统计(期望)','statistical')}</th><th class="n">${L('时域(实测)','time (measured)')}</th></tr></thead><tbody>
   <tr class="key" data-row="local"><td>${L('目标格点 SNR · 目标处的噪底','target cell SNR · the floor where the target is')}</td><td class="n">${f(t.snr_cell_local_expected_db)} dB</td><td class="n">${f(t.snr_cell_local_db)} dB</td></tr>
   <tr><td>${L('差','difference')}</td><td></td><td class="n">${t.snr_local_difference_db==null?'—':fs(t.snr_local_difference_db,2)+' dB'}</td></tr>
   ${t.peak_is_target===false ? `<tr data-row="band"><td colspan="3" style="color:var(--muted)">${L(`图上最高的峰不是目标(是泄漏):"峰 / 全带平均噪底"读出 ${f(t.snr_cell_db)} dB,那是泄漏的,不与目标的期望值比。`,`The map's highest peak is not the target (it is the leakage): "peak over the band's mean floor" reads ${f(t.snr_cell_db)} dB, the leakage's, and is not compared with the target's expectation.`)}</td></tr>`
     : `<tr data-row="band"><td>${L('图上的峰 · 全带平均噪底','map peak · floor averaged over the band')}</td><td class="n">${f(t.snr_cell_expected_db)} dB</td><td class="n">${f(t.snr_cell_db)} dB</td></tr>
   <tr><td>${L('差','difference')}</td><td></td><td class="n">${fs(t.snr_difference_db,2)} dB</td></tr>`}
   <tr><td>${L('峰值位置','peak')}</td><td class="n">${r.target.range_m} m · ${r.target.velocity_mps} m/s</td><td class="n">${f(t.peak_range_interp_m,3)} m · ${f(t.peak_velocity_mps,2)} m/s</td></tr>
   <tr><td>${L('−3 dB 宽度','−3 dB width')}</td><td class="n">${r.nonlin.width_3db_m==null?'—':f(r.nonlin.width_3db_m*100,2)+' cm'}</td><td class="n">${f(t.width_3db_m*100,2)} cm</td></tr>
   <tr><td>${L('CFAR 过门限格','CFAR cells')}</td><td class="n">—</td><td class="n">${r.cells.length}</td></tr>
   </tbody></table></div>`;
}
function reproCard(){
  const r=R(), rp=r.repro; const cp=(t)=>`<button class="btn sm cp" data-act="copy" data-copy="${esc(t)}">${L('复制','Copy')}</button>`;
  return `<div class="card" data-tab="results"><h2>${L('可复现','Reproduce')}</h2>
   <dl class="kv" style="margin-top:8px">
    <dt>seed</dt><dd>${rp.seed}</dd>
    <dt>${L('配置哈希','config hash')}</dt><dd title="${rp.config_sha256}">sha256 ${rp.config_sha256} ${cp(rp.config_sha256)}</dd>
    <dt>${L('库','library')}</dt><dd>${rp.library} ${rp.version}</dd>
    <dt>${L('环境','runtime')}</dt><dd>python ${rp.python} · numpy ${rp.numpy}</dd>
    <dt>vendored</dt><dd>${rp.vendored.map(v=>`${v.repo}@${v.pin.slice(0,7)}`).join(' · ')}</dd>
    <dt>${L('实测耗时','measured')}</dt><dd>${L('统计','statistical')} ${r.wall} s${r.frame?` · ${L('时域','time')} ${r.frame.wall_s} s`:''}</dd>
    <dt>${L('相对默认的改动','edits from the defaults')}</dt><dd>${Object.keys(rp.edits).length?esc(JSON.stringify(rp.edits)):L('无','none')}</dd>
   </dl>
   <pre class="cli">${esc(rp.call)}</pre><p class="sub" style="margin:6px 0 0">${cp(rp.call)} ${L('这一行给出本页的报告(统计引擎)。','This line gives the report on this page (statistical engine).')}</p></div>`;
}

/* ---------- navs, shell ---------- */
const IC = {
 results:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 15h18M9 4v16"/></svg>',
 params:'<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
 budget:'<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
 pn:'<svg viewBox="0 0 24 24"><path d="M3 18c3 0 4-12 6-12s2 9 4 9 2-5 4-5 2 3 4 3"/></svg>',
 bands:'<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>'};

const TABS = [['results','结果','Results'],['params','参数','Params'],['budget','预算·合规','Budget'],['pn','相噪','Phase noise']];
function bnav(){ return `<nav class="bnav" aria-label="sections">${TABS.map(([k,zh,en])=>`<button data-act="mtab" data-tab-to="${k}" class="${S.mtab===k?'on':''}">${IC[k]}<span>${L(zh,en)}</span></button>`).join('')}</nav>`; }
function workbench(){
  const stale = S.error ? `<div class="refusal" data-tab="results params budget pn"><b>${L('配置层不接受这组参数','The config refuses these settings')}</b><span>${esc(S.error.error)}</span><span class="spacer"></span><span style="color:var(--muted)">${L('下面仍是上一组合法参数的结果。','Below is still the last legal run.')}</span></div>` : '';
  return `<div class="wb"><div class="wb-in" data-mtab="${S.mtab}">${paramsPanel()}<div class="main">${stale}${RUN ? kpis()+previewBar()+baselineCard()+runbar()+rdCard()+angleCard()+budgetCard()+complianceCard()+pnCard()+timeCard()+reproCard() : `<div class="empty span2">${L('计算中…','computing…')}</div>`}</div>${bnav()}</div></div>`;
}
function renderTop(){
  document.getElementById('langseg').innerHTML = `<button data-act="lang" data-v="zh" class="${S.lang==='zh'?'on':''}">中</button><button data-act="lang" data-v="en" class="${S.lang==='en'?'on':''}">EN</button>`;
  document.getElementById('themeseg').innerHTML = [['auto',L('自动','Auto')],['light',L('浅','Light')],['dark',L('深','Dark')]].map(([k,l])=>`<button data-act="theme" data-v="${k}" class="${S.theme===k?'on':''}" aria-label="theme ${k}">${l}</button>`).join('');
  document.getElementById('pages').innerHTML = pnav();
  document.documentElement.lang = S.lang==='zh'?'zh-CN':'en';
  if(S.theme==='auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', S.theme);
  const b=document.getElementById('busy'); b.hidden=!(S.pending||S.finalizing); b.textContent = S.pending ? L('计算中','computing') : L('预览 · 逐周期引擎计算中','preview · cycle-accurate run in progress');
}
function render(){
  if(!S.spec) return;
  const act=document.activeElement; const keep = act && act.dataset && act.dataset.path ? {path:act.dataset.path, a:act.selectionStart, b:act.selectionEnd} : null;
  const sc=document.querySelector('.params'); const top=sc?sc.scrollTop:0;
  S.page = route(); renderTop();
  document.getElementById('view').innerHTML = S.page==='system' ? systemPage() : S.page==='bands' ? bandsPage() : S.page==='sweep' ? sweepPage() : workbench();
  const sc2=document.querySelector('.params'); if(sc2) sc2.scrollTop=top;
  if(keep){ const el=document.querySelector(`[data-path="${keep.path}"]`); if(el){ el.focus(); try{ el.setSelectionRange(keep.a, keep.b); }catch(e){} } }
  drawCharts();
}
function drawCharts(){
  if(!RUN) return;
  document.querySelectorAll('.chart').forEach(el=>{
    const w=Math.floor(el.clientWidth); if(w<=0) return;
    const k=el.dataset.chart;
    if(k==='rd') el.innerHTML=rdSvg(w);
    else if(k==='offtime') el.innerHTML=offSvg(w);
    else if(k==='tiers'){ const c=R().compliance; el.innerHTML=tiersSvg(w,c.sweep_ghz,c.governing,c.tiers); }
    else if(k==='lf') el.innerHTML=lfSvg(w);
    else if(k==='ghosts') el.innerHTML=ghostSvg(w);
    else if(k==='sys'){ el.innerHTML=sysSvg(); fitSys(el); }
    else if(k==='levels') el.innerHTML=levelsSvg(w);
    else if(k==='bands'){ if(S.bands && S.bands.applies) el.innerHTML=bandsSvg(w); }
    else if(k==='btiers'){ const r=S.bands && S.bands.rows.find(x=>x.id===S.band); if(r) el.innerHTML=tiersSvg(w, r.sweep_ghz, r.governing, r.tiers); }
    else if(k==='sweep'){ if(S.sweep) el.innerHTML=sweepSvg(w); }
    else if(k==='array') el.innerHTML=arraySvg(w);
    else if(k==='angle') el.innerHTML=angleSvg(w);
  });
}

/* ---------- the loop: an edit, a debounce, one request in flight ---------- */
let timer=null;
function changed(){ S.dirty=true; clearTimeout(timer); timer=setTimeout(compute, 250); }
async function compute(){
  if(S.pending){ S.dirty=true; return; }
  S.pending=true; S.dirty=false; renderTop();
  const body = {values:Object.assign({}, S.values)}; if(S.baseline) body.baseline={values:S.baseline.values, metrics:S.baseline.metrics};
  let res; try{ res = await api('run', Object.assign({preview:true}, body)); }catch(e){ res={ok:false, error:String(e), field:null, inert:S.inert, refused:S.refused}; }
  S.pending=false;
  S.inert=res.inert||{}; S.refused=res.refused||{};
  if(res.ok){ S.run=res; S.error=null; S.values=res.values; S.tags=res.tags; S.resolved=res.resolved; RUN=adapt(res, S.frame); }
  else S.error={error:res.error, field:res.field};
  S.finalSeq++; S.finalizing=false;                       // whatever full run was on its way belongs to older settings
  render();
  if(S.dirty){ compute(); return; }
  S.finalBody = res.ok && res.preview ? body : null;
  if(S.finalBody && !ON_DEVICE) finalize(body);
}
// the answer above was a preview on the linearised chirp engine: fetch the cycle-accurate run of the same settings
async function finalize(body){
  const mine=++S.finalSeq; S.finalizing=true; renderTop();
  let res; try{ res = await api('run', Object.assign({final:true}, body)); }catch(e){ res={ok:false}; }
  if(mine!==S.finalSeq) return;                           // the settings moved on while it ran
  S.finalizing=false;
  if(res.ok && !res.superseded && S.run && res.repro.config_sha256===S.run.repro.config_sha256){ S.run=res; S.tags=res.tags; S.resolved=res.resolved; RUN=adapt(res, S.frame); render(); }
  else renderTop();
}
async function poll(){
  if(!S.job) return;
  let j; try{ j = await api('jobs/'+S.job.id); }catch(e){ return; }
  if(!S.job || j.id!==S.job.id) return;
  S.job=j;
  if(j.status==='done'){ S.frame=j.result; S.lastWall=j.result.wall_s; S.job=null; S.jobMsg=L(`完成 · ${j.result.wall_s} s`,`done · ${j.result.wall_s} s`); if(S.run) RUN=adapt(S.run,S.frame); render(); return; }
  if(j.status==='cancelled'){ S.job=null; S.jobMsg=L(`已在 ${f(j.elapsed_s||0,1)} s 取消;图仍是上一帧`,`cancelled at ${f(j.elapsed_s||0,1)} s; the map is the previous frame`); render(); return; }
  if(j.status==='error'){ S.job=null; S.jobMsg=L('时域引擎出错:','time engine failed: ')+esc(j.error||''); render(); return; }
  const slot=document.getElementById('jobslot'); if(slot) slot.innerHTML=jobHtml();
  setTimeout(poll, 250);
}

// a config file's settings into the form: the library's own loader reads it, the page takes the values it gives back
async function loadYaml(body, label){
  let r; try{ r = await api('yaml/load', body); }catch(e){ r={ok:false, error:String(e)}; }
  if(r.ok){ S.values=r.values; S.yamlMsg={ok:true, text:L(`已载入 ${label}`,`Loaded ${label}`)}; changed(); }
  else S.yamlMsg={ok:false, text:L(`没有载入 ${label}:`,`${label} not loaded: `)+r.error};
  render();
}

/* ---------- events ---------- */
function showPop(tg){
  const pop=document.getElementById('pop'); const src=tg.dataset.src, key=tg.dataset.key, path=tg.dataset.extra; const e=key && S.sources[key];
  let h=`<b>${src} · ${L(...(S.spec.tags[src]||[src,src]))}</b>`;
  if(path && path!=='legend'){ const c=S.spec.controls.find(x=>x.path===path); const r=S.resolved[path];
    h+=`<div class="mono" style="font-size:11.5px">${path}: ${r?disp(c,r.value):'—'} → <b style="display:inline">${disp(c,S.values[path])}</b> ${esc(c.unit)}</div><div class="cite">${L('在界面上改过的数没有外部出处,记为 assumed。','A number edited on the page has no external source and is tagged assumed.')}${r?L(` 原来:${r.source},`,` Was ${r.source}: `)+esc(key):''}</div>`; }
  else if(e) h+=`<div class="mono" style="font-size:11.5px">${key} = ${e.value} ${esc(e.unit||'')}</div><div class="cite">${esc(e.cite||'')}${e.section?' — '+esc(e.section):''}</div>`;
  pop.innerHTML=h; pop.style.display='block';
  const r=tg.getBoundingClientRect(); const pw=pop.offsetWidth;
  let x=r.left+window.scrollX; x=Math.max(16+window.scrollX, Math.min(x, window.scrollX+document.documentElement.clientWidth-pw-16));
  pop.style.left=x+'px'; pop.style.top=(r.bottom+window.scrollY+6)+'px';
}
document.addEventListener('click', async e=>{
  const pop=document.getElementById('pop'); const tg=e.target.closest('.tag, .stag');
  if(tg){ e.preventDefault(); showPop(tg); return; }
  if(!e.target.closest('#pop')) pop.style.display='none';
  const a=e.target.closest('[data-act]'); if(!a) return; const act=a.dataset.act;
  if(act==='lang'){ S.lang=a.dataset.v; save(); render(); }
  else if(act==='theme'){ S.theme=a.dataset.v; save(); renderTop(); }
  else if(act==='reset'){ S.values=Object.assign({}, S.defaults); S.yamlMsg=null; changed(); render(); }
  else if(act==='finalnow'){ if(S.finalBody) finalize(S.finalBody); }
  else if(act==='yamlopen'){ if(ON_DEVICE){ S.yamlPanel={mode:'in', text:''}; render(); } else document.getElementById('yamlfile').click(); }
  else if(act==='yamlclose'){ S.yamlPanel=null; render(); }
  else if(act==='yamltake'){ const text=document.getElementById('yamltext').value; S.yamlPanel=null; await loadYaml({yaml:text}, L('粘贴的文本','the pasted text')); }
  else if(act==='yamlsave'){ const r=await api('yaml/export', {values:S.values});
    if(!r.ok){ S.yamlMsg={ok:false, text:r.error}; render(); return; }
    if(ON_DEVICE){ S.yamlPanel={mode:'out', text:r.yaml, name:r.filename}; S.yamlMsg=null; render(); return; }      // no downloads in a WebView: the text, to copy
    const u=URL.createObjectURL(new Blob([r.yaml], {type:'text/yaml'})); const l=document.createElement('a'); l.href=u; l.download=r.filename; document.body.appendChild(l); l.click(); l.remove(); setTimeout(()=>URL.revokeObjectURL(u), 1000);
    S.yamlMsg={ok:true, text:L(`已导出 ${r.filename}`,`Exported ${r.filename}`)}; render(); }
  else if(act==='dither'){ S.values['lo.tdc_dither_lsb'] = (S.values['lo.tdc_dither_lsb']||0)>0 ? 0 : 1; if(S.values['lo.tdc_dither_lsb']===0) S.values['lo.tdc_dither_gain_error']=0; changed(); render(); }
  else if(act==='frame'){ S.jobMsg=null; const j=await api('frame', {values:S.values}); if(j.status==='error'){ S.jobMsg=esc(j.error); render(); } else { S.job=j; render(); poll(); } }
  else if(act==='cancel'){ if(S.job) await api('jobs/'+S.job.id+'/cancel', {}); }
  else if(act==='mtab'){ S.mtab=a.dataset.tabTo; const w=document.querySelector('.wb-in'); w.dataset.mtab=S.mtab; w.querySelectorAll('.bnav button').forEach(b=>b.classList.toggle('on',b===a)); window.scrollTo(0,0); drawCharts(); }
  else if(act==='sysblk'){ S.sys = S.sys===a.dataset.id ? null : a.dataset.id; const sc=document.querySelector('.sysscroll'); const left=sc?sc.scrollLeft:0; render(); const sc2=document.querySelector('.sysscroll'); if(sc2) sc2.scrollLeft=left; }
  else if(act==='band'){ if(e.target.closest('button')) return; S.band=a.dataset.band; render(); }
  else if(act==='useband'){ const r=S.bands.rows.find(x=>x.id===a.dataset.band); Object.assign(S.values, r.apply); location.hash='#workbench'; changed(); }
  else if(act==='bandsrun'){ S.bandsFor=null; render(); }
  else if(act==='sweeprun'){ const c=swCtl(), E=swEnds(); startJob('sweep', {values:S.run.values, path:S.sw.path, lo:E.lo*c.scale, hi:E.hi*c.scale, points:S.sw.points}); }
  else if(act==='usepoint'){ S.values[S.sweep.path]=S.sweep.points[+a.dataset.pt].x; location.hash='#workbench'; changed(); }
  else if(act==='kcancel'){ const j=S.jobs[a.dataset.kind]; if(j) await api('jobs/'+j.id+'/cancel', {}); }
  else if(act==='pin'){ if(S.run){ S.baseline={values:Object.assign({}, S.run.values), metrics:S.run.metrics, sha:S.run.repro.config_sha256}; compute(); } }
  else if(act==='unpin'){ S.baseline=null; if(S.run) delete S.run.baseline; render(); }
  else if(act==='copy'){ const t=a.dataset.copy; try{ await navigator.clipboard.writeText(t); a.textContent=L('已复制','Copied'); }catch(err){ a.textContent=L('请手动选中复制','select and copy by hand'); } setTimeout(()=>{ a.textContent=L('复制','Copy'); },1200); }
});
document.addEventListener('change', async e=>{
  const el=e.target;
  if(el.dataset && el.dataset.sw){ const k=el.dataset.sw;
    if(k==='path'){ S.sw.path=el.value; S.sw.lo=null; S.sw.hi=null; }
    else if(k==='metric') S.sw.metric=el.value;
    else { const n=parseFloat(el.value.replace('−','-')); if(!isNaN(n)) S.sw[k] = k==='points' ? Math.max(2, Math.min(S.spec.sweep_max_points, Math.round(n))) : n; }
    render(); return; }
  if(el.id==='yamlfile'){ const file=el.files && el.files[0]; if(!file) return; const text=await file.text(); el.value=''; await loadYaml({yaml:text}, file.name); return; }
  if(el.dataset && el.dataset.yaml==='bundled'){ if(el.value) await loadYaml({name:el.value}, el.value+'.yaml'); return; }
  const p=el.dataset && el.dataset.path; if(!p) return; const c=S.spec.controls.find(x=>x.path===p);
  let v=el.value;
  if(el.tagName==='SELECT'){ v = c.kind==='bool' ? v==='true' : (v===''?null:v); }
  else if(v.trim()===''){ if(!c.kind.startsWith('opt_')){ render(); return; } v=null; }
  else if(c.kind==='opt_str'){ v=v.trim(); }
  else { const n=parseFloat(v.replace('−','-')); if(isNaN(n)){ render(); return; } v = (c.kind==='int'||c.kind==='opt_int') ? Math.round(n) : n*c.scale; }
  if(p==='band.kind'){ const r=await api('band', {values:S.values, kind:v}); if(r.values) S.values=r.values; }
  else S.values[p]=v;
  changed();
});
document.addEventListener('toggle', e=>{ const d=e.target; if(d.dataset && d.dataset.key) S.open[d.dataset.key]=d.open; }, true);
document.addEventListener('keydown', e=>{ if(e.key==='Escape') document.getElementById('pop').style.display='none'; if(e.key==='Enter' && e.target.dataset && e.target.dataset.path) e.target.blur(); });
window.addEventListener('hashchange', ()=>{ window.scrollTo(0,0); render(); });
let rz=null; window.addEventListener('resize', ()=>{ clearTimeout(rz); rz=setTimeout(drawCharts,120); });

(async function boot(){
  const [ver, spec, cfg, src, cfgs] = await Promise.all([api('version'), api('spec'), api('config'), api('sources'), api('configs')]);
  S.bundled=cfgs.bundled||[];
  S.spec=spec; S.sources=src.entries; S.values=cfg.values; S.defaults=Object.assign({}, cfg.values); S.tags=cfg.tags; S.inert=cfg.inert; S.refused=cfg.refused;
  S.resolved={}; spec.controls.forEach(c=>{ if(c.source) S.resolved[c.path]={value:c.resolved, source:c.source, key:c.sources_key}; });
  document.getElementById('ver').textContent = ver.version;
  window.D = {sources:S.sources};
  render(); compute();
})();
