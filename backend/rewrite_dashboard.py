import re
import os

html_content = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evidence Desk — Social Bias Auditor</title>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #111113; --bg-surface: #1a1a1e; --bg-card: rgba(255,255,255,0.03);
  --border: rgba(255,255,255,0.08); --border-active: rgba(255,255,255,0.16);
  --ink: #e8e6e1; --ink2: rgba(232,230,225,0.7); --muted: rgba(232,230,225,0.4);
  --left: #4a6fa5; --center: #8a8a7a; --right: #a54a4a;
  --green: #5a9a6a; --orange: #c9873a; --accent: #b8a070;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;font-size:14px;line-height:1.6}
h1,h2,h3,.serif{font-family:'Source Serif 4','Georgia',serif}
.app{max-width:1200px;margin:0 auto;padding:0 32px;padding-bottom:100px}

/* ── Status Strip ── */
.status-strip{padding:10px 0;border-bottom:1px solid var(--border);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px;letter-spacing:0.4px;text-transform:uppercase}
.status-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.status-dot.connected{background:var(--green);box-shadow:0 0 6px var(--green)}
.status-dot.disconnected{background:var(--right);box-shadow:0 0 6px var(--right)}

/* ── Header ── */
.header{padding:40px 0 32px;border-bottom:1px solid var(--border)}
.header h1{font-size:28px;font-weight:700;color:var(--ink);letter-spacing:-0.5px}
.header-sub{font-size:13px;color:var(--muted);margin-top:6px}

/* ── Tabs ── */
.tabs{display:flex;gap:24px;border-bottom:1px solid var(--border);margin-top:0}
.tab{padding:16px 0;font-size:13px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;transition:.2s;letter-spacing:0.2px}
.tab:hover{color:var(--ink2)}
.tab.active{color:var(--ink);border-bottom-color:var(--accent)}

/* ── Bento Grid (Analytics) ── */
.bento-grid{display:grid;grid-template-columns:repeat(12, 1fr);gap:20px;padding:32px 0;border-bottom:1px solid var(--border)}
.bento-card{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:24px;display:flex;flex-direction:column}
.bento-title{font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;margin-bottom:8px;color:var(--ink)}
.bento-sub{font-size:12px;color:var(--muted);margin-bottom:16px}

/* Card 1: Concentration */
.col-conc{grid-column:span 4}
.rigidity-pct{font-family:'Source Serif 4',serif;font-size:48px;font-weight:700;letter-spacing:-1.5px;line-height:1}
.rigidity-qualifier{font-size:12px;color:var(--muted);background:rgba(255,255,255,0.05);padding:3px 10px;border-radius:6px;display:inline-block;margin-bottom:12px;margin-top:12px}
.rigidity-why{font-size:13px;color:var(--orange);font-style:italic;margin-top:auto}

/* Card 2: L/C/R Breakdown */
.col-brk{grid-column:span 8}
.lcr-stats{display:flex;gap:24px;margin-bottom:24px}
.lcr-stat{flex:1}
.lcr-num{font-size:28px;font-weight:700;font-family:'Source Serif 4',serif;line-height:1;margin-bottom:4px}
.lcr-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px}
.rigidity-bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:rgba(255,255,255,0.04);margin-bottom:8px}
.rigidity-bar>div{transition:width .6s ease}
.rbar-l{background:var(--left)}.rbar-c{background:var(--center)}.rbar-r{background:var(--right)}

/* Card 3: Perspective Map */
.col-map{grid-column:span 12}
.pmap{position:relative;height:140px;margin-top:10px}
.pmap-axis{position:absolute;bottom:20px;left:0;right:0;height:1px;background:linear-gradient(90deg,var(--left),var(--center) 50%,var(--right))}
.pmap-labels{position:absolute;bottom:0;left:0;right:0;display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.pmap-dot{position:absolute;border-radius:50%;transform:translate(-50%,-50%);transition:all .3s;cursor:default;box-shadow:0 0 10px rgba(0,0,0,0.5)}
.pmap-dot:hover{transform:translate(-50%,-50%) scale(1.2);z-index:10}

/* Card 4: Drift */
.col-drift{grid-column:span 12}
.rigidity-drift{display:flex;align-items:flex-end;gap:2px;height:100px;margin-top:auto}
.rigidity-drift>div{flex:1;border-radius:2px 2px 0 0;transition:height .3s;opacity:0.8}
.rigidity-drift>div:hover{opacity:1}

/* ── Stories Data-Dense Layout ── */
.tab-content{display:none;padding:32px 0}.tab-content.active{display:block}
.cluster{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;margin-bottom:24px;overflow:hidden}
.cluster-header{padding:20px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.01)}
.cluster-label{font-family:'Source Serif 4',serif;font-size:18px;font-weight:600}
.cluster-meta{display:flex;align-items:center;gap:12px;font-size:12px;color:var(--muted)}
.cluster-lean{font-size:10px;font-weight:700;padding:3px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:0.5px}

.cluster-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.cluster-col{padding:20px 24px}
.cap-col{border-right:1px solid var(--border)}
.col-header{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:16px}

/* Capture Item */
.cap-item{padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;gap:12px}
.cap-item:last-child{border-bottom:none}
.cap-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:6px}
.cap-body{flex:1;min-width:0}
.cap-source{font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:4px}
.cap-text{font-size:13px;color:var(--ink2);line-height:1.6}
.cap-meta{font-size:11px;color:var(--muted);margin-top:6px;display:flex;gap:8px;align-items:center}
.cap-score{font-size:13px;font-weight:700;font-variant-numeric:tabular-nums;flex-shrink:0}

/* Source Tags */
.src-tag{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.4px}
.src-allsides{background:rgba(90,154,106,0.15);color:var(--green)}
.src-gdelt{background:rgba(74,111,165,0.15);color:var(--left)}
.src-pabs{background:rgba(201,135,58,0.15);color:var(--orange)}
.src-qbias{background:rgba(138,138,122,0.15);color:var(--center)}

/* Alternate Card */
.alt-card{padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;margin-bottom:12px;display:flex;gap:12px;transition:.2s}
.alt-card:hover{background:rgba(255,255,255,0.04);border-color:var(--border-active)}
.alt-bar{width:4px;border-radius:2px;align-self:stretch;flex-shrink:0}
.alt-info{flex:1;min-width:0}
.alt-title{font-size:14px;font-weight:500;margin-bottom:6px;line-height:1.4}
.alt-title a{color:var(--ink);text-decoration:none}
.alt-title a:hover{text-decoration:underline}
.alt-meta{font-size:11px;color:var(--muted);display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
.alt-conf{display:flex;align-items:center;gap:4px}
.alt-conf-bar{width:30px;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden}
.alt-conf-fill{height:100%;border-radius:2px;background:var(--green)}
.no-alts{font-size:13px;color:var(--muted);font-style:italic;padding:12px;background:rgba(255,255,255,0.02);border-radius:8px}

.rel-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.4px}
.rel-high{background:rgba(90,154,106,0.2);color:var(--green)}
.rel-moderate{background:rgba(201,135,58,0.2);color:var(--orange)}
.rel-low{background:rgba(165,74,74,0.15);color:var(--right)}
.rel-unknown{background:rgba(138,138,122,0.15);color:var(--center)}
.persp-diff{font-size:12px;color:var(--ink2);padding-top:6px;border-top:1px dashed rgba(255,255,255,0.08)}
.conf-qual{font-size:10px;color:var(--muted);padding:1px 6px;border:1px solid var(--border);border-radius:4px}

.bias-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:0.3px}
.bias-left{background:rgba(74,111,165,0.2);color:var(--left)}
.bias-center{background:rgba(138,138,122,0.2);color:var(--center)}
.bias-right{background:rgba(165,74,74,0.2);color:var(--right)}

/* ── Methodology ── */
.methodology{margin-top:32px;padding:24px;border:1px solid var(--border);border-radius:12px;background:rgba(255,255,255,0.01)}
.meth-title{font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;margin-bottom:12px}
.meth-inner{font-size:12px;color:var(--ink2);line-height:1.7;column-count:2;column-gap:32px}

/* ── Corpus Browser ── */
.browser-filters{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap}
.bfilt{font-size:12px;font-weight:500;padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--muted);cursor:pointer;transition:.2s}
.bfilt:hover{border-color:var(--border-active);color:var(--ink2)}
.bfilt.active{background:rgba(184,160,112,0.15);border-color:var(--accent);color:var(--accent)}
.ctable{width:100%;border-collapse:collapse;background:var(--bg-card);border-radius:12px;overflow:hidden;border:1px solid var(--border)}
.ctable th{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:var(--muted);text-align:left;padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;background:rgba(255,255,255,0.02)}
.ctable td{padding:12px 16px;font-size:13px;border-bottom:1px solid rgba(255,255,255,0.03)}
.ctable tr:last-child td{border-bottom:none}
.ctable tr:hover td{background:rgba(255,255,255,0.03)}
.page-nav{display:flex;justify-content:center;gap:12px;margin-top:20px}

::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:3px}
@media(max-width:900px){
  .bento-card{grid-column:span 12 !important}
  .cluster-grid{grid-template-columns:1fr}
  .cap-col{border-right:none;border-bottom:1px solid var(--border)}
  .meth-inner{column-count:1}
}
</style>
</head>
<body>
<div class="app">

  <div class="status-strip" id="statusStrip">
    <div class="status-dot disconnected" id="statusDot"></div>
    <span id="statusText">Connecting to companion service…</span>
  </div>

  <div class="header">
    <h1>Evidence Desk</h1>
    <div class="header-sub">Bias exposure analysis · Fused corpus of 20,336 sources (AllSides + GDELT + Qbias + PABS)</div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="analytics">Analytics</div>
    <div class="tab" data-tab="stories">Stories</div>
    <div class="tab" data-tab="corpus">Corpus</div>
  </div>

  <!-- Analytics Bento Grid -->
  <div class="tab-content active" id="tab-analytics">
    <div class="bento-grid" id="rigidityPanel">
      
      <!-- Concentration -->
      <div class="bento-card col-conc">
        <div class="bento-title">Echo Chamber Concentration</div>
        <div class="bento-sub">Inverse variance of structural bias over window.</div>
        <div class="rigidity-pct" id="rigPct">—</div>
        <div><span class="rigidity-qualifier" id="rigQual">no evidence</span></div>
        <div class="rigidity-why" id="rigWhy">Waiting for captures…</div>
      </div>

      <!-- Breakdown -->
      <div class="bento-card col-brk">
        <div class="bento-title">Exposure Distribution</div>
        <div class="bento-sub" id="rigCoverage">Waiting for captures…</div>
        <div class="lcr-stats">
          <div class="lcr-stat"><div class="lcr-num" id="statLeft" style="color:var(--left)">0</div><div class="lcr-label">Left</div></div>
          <div class="lcr-stat"><div class="lcr-num" id="statCenter" style="color:var(--center)">0</div><div class="lcr-label">Center</div></div>
          <div class="lcr-stat"><div class="lcr-num" id="statRight" style="color:var(--right)">0</div><div class="lcr-label">Right</div></div>
        </div>
        <div class="rigidity-bar" id="rigBar">
          <div class="rbar-l" style="width:33%"></div>
          <div class="rbar-c" style="width:34%"></div>
          <div class="rbar-r" style="width:33%"></div>
        </div>
      </div>

      <!-- Perspective Map -->
      <div class="bento-card col-map">
        <div class="bento-title">Perspective Map</div>
        <div class="bento-sub">Each dot is a unique source. Size shows frequency. Opacity shows confidence.</div>
        <div class="pmap" id="perspectiveMap">
          <div class="pmap-axis"></div>
          <div class="pmap-labels"><span>Far Left</span><span>Left</span><span>Center</span><span>Right</span><span>Far Right</span></div>
        </div>
      </div>

      <!-- Drift -->
      <div class="bento-card col-drift">
        <div class="bento-title">Bias Drift Timeline</div>
        <div class="bento-sub">Moving average of your ideological exposure over time.</div>
        <div class="rigidity-drift" id="rigDrift"></div>
      </div>

    </div>
  </div>

  <!-- Stories Tab -->
  <div class="tab-content" id="tab-stories">
    <div style="font-size:13px;color:var(--muted);margin-bottom:24px" id="clusterSummary">Captures will be grouped by topic as they arrive.</div>
    <div id="clusterList"></div>
  </div>

  <!-- Corpus Tab -->
  <div class="tab-content" id="tab-corpus">
    <div class="bento-title" style="margin-bottom:8px">Fused Source Corpus</div>
    <div class="bento-sub" style="margin-bottom:24px">Browse all 20,336 scored domains and handles across four datasets.</div>
    <div class="browser-filters" id="browserFilters">
      <button class="bfilt active" data-filter="">All</button>
      <button class="bfilt" data-filter="handles">Handles</button>
      <button class="bfilt" data-filter="domains">Domains</button>
      <button class="bfilt" data-filter="left">Left</button>
      <button class="bfilt" data-filter="center">Center</button>
      <button class="bfilt" data-filter="right">Right</button>
      <button class="bfilt" data-filter="high_conf">High Conf.</button>
      <button class="bfilt" data-filter="multi_source">Multi-Source</button>
    </div>
    <table class="ctable"><thead><tr>
      <th data-sort="alpha">Source</th><th data-sort="score">Score</th>
      <th data-sort="confidence">Confidence</th><th>Position</th><th data-sort="sources">Datasets</th>
    </tr></thead><tbody id="corpusBody"></tbody></table>
    <div class="page-nav" id="pageNav"></div>
  </div>

  <!-- Methodology -->
  <div class="methodology">
    <div class="meth-title">Methodology & Limitations</div>
    <div class="meth-inner">
      <strong>What scores represent:</strong> Source-position scores reflect the historical/structural ideological positioning of linked sources and accounts as measured across four independent datasets. They do <em>not</em> measure the truthfulness, quality, or political intent of any individual post.<br><br>
      <strong>Concentration metric:</strong> Exposure concentration is computed as the inverse of score variance across a rolling window. High concentration means the feed clusters around a narrow band of the ideological spectrum. The metric intentionally avoids causal claims about behavior.<br><br>
      <strong>Alternate coverage:</strong> Alternate articles are retrieved via Google News RSS and cross-referenced against the fused corpus for bias labeling. Relevance depends on keyword extraction quality; not all matches describe the same event.<br><br>
      <strong>Confidence:</strong> Multi-dataset corroboration increases confidence. Scores from a single dataset are labeled "single-dataset".<br><br>
      <strong>Privacy:</strong> The core rigidity score runs entirely in-browser with zero telemetry. This companion dashboard receives captured domains/handles and tweet text to provide alternate coverage — a deliberate architectural trade-off documented in the dual-trust model.
    </div>
  </div>

</div>

<script>
let cFilter='',cSort='score',cOffset=0;const PS=50;
let lastEventTime=0,connectionOk=false;

document.querySelectorAll('.tab').forEach(t=>{t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');document.getElementById('tab-'+t.dataset.tab).classList.add('active');
  if(t.dataset.tab==='corpus')loadCorpus();
})});

async function refresh(){
  try{
    const r=await fetch('/api/feed');const d=await r.json();
    connectionOk=true;lastEventTime=Date.now();
    renderStatus(d);renderRigidity(d.rigidity);renderMap(d.perspective_dots);renderClusters(d.clusters);
  }catch(e){connectionOk=false;renderStatusDisconnected();console.error(e)}
}

function renderStatus(d){
  const s=d.stats;
  const dot=document.getElementById('statusDot');
  dot.className='status-dot connected';
  const ago=s.total>0?Math.round((Date.now()-lastEventTime)/1000):0;
  document.getElementById('statusText').textContent=
    `Companion connected · ${s.total} captures · ${s.unique_sources} unique sources${ago>0?' · Last event '+ago+'s ago':''}`;
}
function renderStatusDisconnected(){
  document.getElementById('statusDot').className='status-dot disconnected';
  document.getElementById('statusText').innerHTML='Backend unavailable — <a href="javascript:void(0)" onclick="refresh()" style="color:var(--orange);text-decoration:underline">retry</a> or start companion service';
}

function renderRigidity(r){
  if(!r)return;
  const pctEl=document.getElementById('rigPct');
  const qualEl=document.getElementById('rigQual');
  const covEl=document.getElementById('rigCoverage');
  const whyEl=document.getElementById('rigWhy');

  if(r.state==='waiting'){
    pctEl.textContent='—';qualEl.textContent='no evidence';
    covEl.textContent='Waiting for captures…';whyEl.textContent='Insufficient data';return;
  }
  pctEl.textContent=r.concentration_pct+'%';
  pctEl.style.color=r.concentration_pct>70?'var(--right)':r.concentration_pct>40?'var(--orange)':'var(--green)';
  qualEl.textContent=r.confidence_qualifier;
  covEl.textContent=r.matched+' matched / '+r.scanned+' posts scanned';
  whyEl.textContent=r.why_changed?'Why this changed: '+r.why_changed:'';

  document.getElementById('statLeft').textContent=r.left;
  document.getElementById('statCenter').textContent=r.center;
  document.getElementById('statRight').textContent=r.right;

  const tot=r.left+r.center+r.right||1;
  const bar=document.getElementById('rigBar');
  bar.querySelector('.rbar-l').style.width=(r.left/tot*100)+'%';
  bar.querySelector('.rbar-c').style.width=(r.center/tot*100)+'%';
  bar.querySelector('.rbar-r').style.width=(r.right/tot*100)+'%';

  const drift=document.getElementById('rigDrift');
  if(r.drift&&r.drift.length>1){
    const mx=Math.max(...r.drift.map(v=>Math.abs(v)),0.1);
    drift.innerHTML=r.drift.map(v=>{
      const h=Math.max(2,Math.abs(v)/mx*100);
      const c=v<-0.1?'var(--left)':v>0.1?'var(--right)':'var(--center)';
      return '<div style="height:'+h+'%;background:'+c+'" title="'+v+'"></div>';
    }).join('');
  }
}

function renderMap(dots){
  const map=document.getElementById('perspectiveMap');
  if(!dots||!dots.length){map.innerHTML='<div class="pmap-axis"></div><div class="pmap-labels"><span>Far Left</span><span>Left</span><span>Center</span><span>Right</span><span>Far Right</span></div>';return;}
  const maxCount=Math.max(...dots.map(d=>d.count));
  let html='<div class="pmap-axis"></div><div class="pmap-labels"><span>Far Left</span><span>Left</span><span>Center</span><span>Right</span><span>Far Right</span></div>';
  dots.forEach(d=>{
    const leftPct=((d.score+1)/2)*100;
    const size=Math.max(8,Math.min(30,(d.count/maxCount)*26+6));
    const opacity=Math.max(0.3,Math.min(0.9,d.confidence));
    const c=d.score<-0.3?'var(--left)':d.score>0.3?'var(--right)':'var(--center)';
    const bottom=25+Math.random()*90;
    html+='<div class="pmap-dot" style="left:'+leftPct+'%;bottom:'+bottom+'px;width:'+size+'px;height:'+size+'px;background:'+c+';opacity:'+opacity+'" title="'+esc(d.value)+': '+d.score.toFixed(2)+' (×'+d.count+')"></div>';
  });
  map.innerHTML=html;
}

function renderClusters(clusters){
  if(!clusters||!clusters.length){
    document.getElementById('clusterList').innerHTML='<div style="color:var(--muted);font-style:italic">No stories captured yet. Browse X/Twitter with the extension active.</div>';
    document.getElementById('clusterSummary').textContent='Captures will be grouped by topic as they arrive.';
    return;
  }
  document.getElementById('clusterSummary').textContent=clusters.length+' story cluster'+(clusters.length>1?'s':'')+' identified from captured posts.';
  document.getElementById('clusterList').innerHTML=clusters.map(cl=>{
    const leanClass=cl.lean.includes('Left')?'bias-left':cl.lean.includes('Right')?'bias-right':'bias-center';
    
    // Captures
    const itemsHtml=cl.items.map(it=>{
      const icon=it.type==='handle'?'@':'';
      const bc=it.score<-0.3?'bias-left':it.score>0.3?'bias-right':'bias-center';
      const srcs=(it.sources||[]).map(s=>'<span class="src-tag src-'+s+'">'+s+'</span>').join(' ');
      return '<div class="cap-item">'+
        '<div class="cap-dot" style="background:'+it.color+'"></div>'+
        '<div class="cap-body">'+
          '<div class="cap-source">'+icon+esc(it.value)+' <span class="bias-badge '+bc+'">'+it.bias_label+'</span></div>'+
          (it.tweet_text?'<div class="cap-text">'+esc(it.tweet_text)+'</div>':'')+
          '<div class="cap-meta">'+srcs+' <span>'+(it.confidence*100).toFixed(0)+'% conf</span></div>'+
        '</div>'+
        '<div class="cap-score" style="color:'+it.color+'">'+it.score.toFixed(2)+'</div>'+
      '</div>';
    }).join('');

    // Alternates
    let altsHtml='';
    if(cl.alternatives&&cl.alternatives.length){
      const seen=new Set();
      cl.alternatives.forEach(a=>{
        if(seen.has(a.domain))return;seen.add(a.domain);
        const abc=a.bias_score<-0.3?'bias-left':a.bias_score>0.3?'bias-right':'bias-center';
        const relClass='rel-'+(a.relevance_label||'unknown');
        const relText=a.relevance_label==='high'?'High relevance':a.relevance_label==='moderate'?'Moderate relevance':a.relevance_label==='low'?'Low relevance':'Relevance unknown';
        altsHtml+='<div class="alt-card">'+
          '<div class="alt-bar" style="background:'+a.color+'"></div>'+
          '<div class="alt-info">'+
            '<div class="alt-title"><a href="'+esc(a.url)+'" target="_blank">'+esc(a.title)+'</a></div>'+
            '<div class="alt-meta">'+
              '<span>'+esc(a.source_name||a.domain)+'</span> '+
              '<span class="bias-badge '+abc+'">'+a.bias_label+'</span> '+
              '<span class="rel-badge '+relClass+'">'+relText+'</span> '+
              '<span class="alt-conf"><span class="alt-conf-bar"><span class="alt-conf-fill" style="width:'+(a.confidence*100)+'%"></span></span>'+(a.confidence*100).toFixed(0)+'%</span> '+
              '<span class="conf-qual">'+(a.confidence_qualifier||'')+'</span>'+
              (a.published?' <span>'+formatDate(a.published)+'</span>':'')+
            '</div>'+
            (a.perspective_diff?'<div class="persp-diff">'+esc(a.perspective_diff)+'</div>':'')+
          '</div>'+
        '</div>';
      });
    } else {
      altsHtml='<div class="no-alts">No corpus-verified alternate coverage available. This may reflect limited keyword overlap with current news, not an absence of other perspectives.</div>';
    }

    return '<div class="cluster">'+
      '<div class="cluster-header">'+
        '<div><span class="cluster-label">'+esc(cl.label)+'</span></div>'+
        '<div class="cluster-meta">'+
          '<span>'+cl.count+' exposure'+(cl.count>1?'s':'')+'</span>'+
          '<span class="cluster-lean '+leanClass+'">'+cl.lean+'</span>'+
        '</div>'+
      '</div>'+
      '<div class="cluster-grid">'+
        '<div class="cluster-col cap-col">'+
          '<div class="col-header">Your Exposure</div>'+
          itemsHtml+
        '</div>'+
        '<div class="cluster-col alt-col">'+
          '<div class="col-header">Alternate Coverage</div>'+
          altsHtml+
        '</div>'+
      '</div>'+
    '</div>';
  }).join('');
}

function loadCorpus(){
  fetch('/api/corpus/browse?offset='+cOffset+'&limit='+PS+'&filter='+cFilter+'&sort='+cSort)
    .then(r=>r.json()).then(renderCorpus).catch(console.error);
}
function renderCorpus(d){
  document.getElementById('corpusBody').innerHTML=d.entries.map(e=>{
    const bc=e.score<-0.3?'bias-left':e.score>0.3?'bias-right':'bias-center';
    const srcs=e.sources.map(s=>'<span class="src-tag src-'+s+'">'+s+'</span>').join(' ');
    return '<tr><td style="font-weight:600">'+esc(e.key)+'</td>'+
    '<td><span style="color:'+e.color+';font-weight:700">'+e.score.toFixed(3)+'</span></td>'+
    '<td><span class="alt-conf"><span class="alt-conf-bar"><span class="alt-conf-fill" style="width:'+(e.confidence*100)+'%"></span></span>'+(e.confidence*100).toFixed(0)+'%</span></td>'+
    '<td><span class="bias-badge '+bc+'">'+e.label+'</span></td>'+
    '<td>'+srcs+'</td></tr>';
  }).join('');
  const tp=Math.ceil(d.total/PS),cp=Math.floor(cOffset/PS)+1;
  document.getElementById('pageNav').innerHTML=
    '<button class="bfilt" '+(cOffset<=0?'disabled':'')+' onclick="cOffset-='+PS+';loadCorpus()">← Prev</button>'+
    '<span style="font-size:12px;color:var(--muted);padding:6px 12px">Page '+cp+' of '+tp+' ('+d.total.toLocaleString()+' entries)</span>'+
    '<button class="bfilt" '+(cOffset+PS>=d.total?'disabled':'')+' onclick="cOffset+='+PS+';loadCorpus()">Next →</button>';
}
document.getElementById('browserFilters').addEventListener('click',e=>{if(e.target.classList.contains('bfilt')){
  document.querySelectorAll('#browserFilters .bfilt').forEach(b=>b.classList.remove('active'));
  e.target.classList.add('active');cFilter=e.target.dataset.filter;cOffset=0;loadCorpus();
}});
document.querySelectorAll('.ctable th[data-sort]').forEach(th=>{th.addEventListener('click',()=>{cSort=th.dataset.sort;cOffset=0;loadCorpus()})});

function esc(s){if(!s)return'';const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function formatDate(s){try{const d=new Date(s);return d.toLocaleDateString('en-US',{month:'short',day:'numeric'})}catch(e){return''}}

refresh();setInterval(refresh,4000);
</script>
</body>
</html>'''

with open('d:/Project/Research_all_real_data/Research/social_bias_auditor/backend/server.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace everything from DASHBOARD_HTML = r"""<!DOCTYPE html> to the end of the file.
pattern = re.compile(r'DASHBOARD_HTML = r"""<!DOCTYPE html>.*', re.DOTALL)
new_text = pattern.sub(f'DASHBOARD_HTML = r"""{html_content}"""', text)

with open('d:/Project/Research_all_real_data/Research/social_bias_auditor/backend/server.py', 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Rewrote DASHBOARD_HTML in server.py")
