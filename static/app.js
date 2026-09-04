let selected=null;
let appMode="DEMO";
let refreshSeconds=10;
const $=x=>document.querySelector(x);
function badge(s){let c=s==="RUNNING"?"green":s==="DELAYED"?"amber":s==="AT STATION"?"blue":s==="CANCELLED"?"red":"blue";return `<span class="badge ${c}">${s}</span>`}
function clock(){let d=new Date();$("#clock").textContent=d.toLocaleTimeString("en-IN",{hour12:false})}
async function api(url,opt){let r=await fetch(url,opt);let j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);return j}
async function loadConfig(){
 try{
  const c=await api("/api/config"); appMode=c.mode; refreshSeconds=c.refresh_seconds||10;
  $("#modeLabel").textContent=appMode==="LIVE"?"LIVE RAIL DATA":"DEMO / SIMULATION";
  $("#modeLabel").className=appMode==="LIVE"?"mode live-mode":"mode demo-mode";
  $("#providerLabel").textContent=c.provider;
  $("#refreshLabel").textContent=appMode==="LIVE"?`Provider refresh: ${refreshSeconds}s`:`Simulation refresh: ${refreshSeconds}s`;
 }catch(e){console.warn(e)}
}
async function loadTrains(force=false){
 try{
  if(appMode==="DEMO" && force){try{await api("/api/live/tick",{method:"POST"})}catch(e){}}
  const q=$("#search").value.trim();
  const data=await api("/api/trains"+(q?"?q="+encodeURIComponent(q)+(force?"&force=1":""):(force?"?force=1":"")));
  const trains=data.trains||[]; const tbody=$("#trains"); tbody.innerHTML="";
  if(!trains.length){
    const msg=data.errors?.length ? (data.errors[0].error||"Live train unavailable") : "No train found";
    tbody.innerHTML=`<tr><td colspan="9"><div class="empty">No live train found for this search.<br><small>${msg}</small></div></td></tr>`;
  }
  let delayed=0,avg=0;
  trains.forEach(t=>{if(t.delay>=10)delayed++;avg+=Number(t.confidence||0);
   tbody.innerHTML+=`<tr class="${selected===t.train_no?'selected-row':''}"><td><div class="train">${t.train_no} · ${t.name}</div><div class="route">${t.category||""} · ${t.zone||""}</div></td><td>${t.origin||"—"}<br>→ ${t.destination||"—"}</td><td>${badge(t.status)}</td><td><b>${t.speed ?? "—"}</b> km/h</td><td><b>${(t.early_minutes||0)>0 ? `${t.early_minutes} min early` : `${t.delay ?? 0} min`}</b></td><td>${t.next_station||"—"}</td><td><b>${t.next_eta||"—"}</b></td><td>${t.confidence!=null?t.confidence+"%":"—"}</td><td><button class="view" onclick="selectTrain('${t.train_no}')">View</button></td></tr>`;
  });
  $("#stats").innerHTML=`<div class="stat"><label>TRAINS MONITORED</label><b>${trains.length}</b><small>${appMode==="LIVE"?"● live provider coverage":"● demo feed"}</small></div><div class="stat"><label>ON TIME / LOW DELAY</label><b>${trains.filter(x=>(x.delay||0)<10).length}</b><small>Dynamic status</small></div><div class="stat"><label>ACTIVE DELAYS</label><b>${delayed}</b><small>Needs attention</small></div><div class="stat"><label>AVG FORECAST CONF.</label><b>${trains.length?Math.round(avg/trains.length):0}%</b><small>${appMode==="LIVE"?"Live forecast input":"Model demo"}</small></div>`;
  $("#updated").textContent=(appMode==="LIVE"?"Live feed checked ":"Updated ")+new Date().toLocaleTimeString();
  if(selected && trains.some(t=>t.train_no===selected)) await selectTrain(selected);
 }catch(e){console.error(e);$("#updated").textContent="Data unavailable";}
}
async function selectTrain(no){
 selected=no;
 try{
  const [t,st,ev]=await Promise.all([api(`/api/trains/${no}`),api(`/api/trains/${no}/stations`),api(`/api/trains/${no}/events`)]);
  $("#detailTitle").textContent=`${t.train_no} · ${t.name}`;
  const statusHost=$("#detailStatus"); statusHost.outerHTML=`<span class="badge ${t.status==="RUNNING"?"green":t.status==="DELAYED"?"amber":t.status==="AT STATION"?"blue":"red"}" id="detailStatus">${t.status}</span>`;
  let stations=(st||[]).filter(s=>s.status!=="departed").slice(0,8).map(s=>`<div class="station"><span><b>${s.station}</b><br><small>${s.scheduled||"—"} scheduled</small></span><span style="text-align:right"><b>${s.eta||"—"}</b><br><small>+${s.predicted_delay??0}m · ${s.confidence??"—"}%</small></span></div>`).join("");
  if(!stations) stations=`<div class="empty">No route forecast available.</div>`;
  let events=(ev||[]).length?ev.map(e=>`<div class="event"><b>${e.event_type||"EVENT"}${e.impact!=null?` · ${e.impact>0?"+":""}${e.impact} min`:""}</b><small>${e.message||""}<br>${e.created||""}</small></div>`).join(""):`<div class="empty">No recent events</div>`;
  const source=t.is_live?`Live source: ${t.data_source}`:"Demo source";
  $("#detailBody").innerHTML=`<div class="bigeta">${t.next_eta||"—"}</div><div style="font-size:10px;color:#667085">Next-station ETA · forecast confidence ${t.confidence??"—"}% · ${source}</div><div class="kv"><div><small>Current speed</small><b>${t.speed ?? "—"} km/h</b></div><div><small>Current delay</small><b>${(t.early_minutes||0)>0 ? `${t.early_minutes} min early` : `${t.delay ?? 0} min`}</b></div><div><small>Next station</small><b>${t.next_station||"—"}</b></div><div><small>Platform</small><b>${t.platform||"TBD"}</b></div><div><small>Position</small><b>${t.lat!=null&&t.lon!=null?Number(t.lat).toFixed(3)+", "+Number(t.lon).toFixed(3):"Not supplied"}</b></div><div><small>Updated</small><b>${formatUpdated(t.updated)}</b></div></div><button class="btn" onclick="refreshSelected('${t.train_no}')">⚡ Refresh live data</button><div class="section"><h3>Upcoming ETA Forecast</h3>${stations}</div><div class="section"><h3>Delay / Event Feed</h3>${events}</div>`;
 }catch(e){$("#detailBody").innerHTML=`<div class="empty">Unable to load this train right now.<br><small>${e.message}</small></div>`}
}
function formatUpdated(v){if(!v)return"—";try{return new Date(v).toLocaleTimeString("en-IN",{hour12:false})}catch(e){return String(v).slice(11,19)}}
async function refreshSelected(no){try{await api(`/api/trains/${no}`);await loadTrains(true);await selectTrain(no)}catch(e){alert("Live data refresh failed: "+e.message)}}
setInterval(()=>{clock();},1000);
loadConfig().then(()=>{loadTrains(false);setInterval(()=>loadTrains(true),Math.max(60000,refreshSeconds*1000));});
$("#search").addEventListener("keydown",e=>{if(e.key==="Enter")loadTrains(false)});
clock();
