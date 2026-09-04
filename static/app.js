let selected=null;
const $=x=>document.querySelector(x);
function badge(s){let c=s==="RUNNING"?"green":s==="DELAYED"?"amber":s==="AT STATION"?"blue":"red";return `<span class="badge ${c}">${s}</span>`}
function clock(){let d=new Date();$("#clock").textContent=d.toLocaleTimeString("en-IN",{hour12:false})}
async function api(url,opt){let r=await fetch(url,opt);return r.json()}
async function loadTrains(doTick=true){
 if(doTick) { try { await api("/api/live/tick",{method:"POST"}); } catch(e) {} }
 const q=$("#search").value.trim(); const data=await api("/api/trains"+(q?"?q="+encodeURIComponent(q):""));
 const tbody=$("#trains"); tbody.innerHTML="";
 let delays=0, delayed=0, avg=0;
 data.forEach(t=>{delays+=t.delay; if(t.delay>=10)delayed++; avg+=Math.max(0,95-t.delay*1.2);
 tbody.innerHTML+=`<tr class="${selected===t.train_no?'selected-row':''}"><td><div class="train">${t.train_no} · ${t.name}</div><div class="route">${t.category} · ${t.zone}</div></td><td>${t.origin}<br>→ ${t.destination}</td><td>${badge(t.status)}</td><td><b>${t.speed}</b> km/h</td><td><b>${t.delay} min</b></td><td>${t.next_station}</td><td><b>${t.next_eta||etaFromDelay(t.delay)}</b></td><td>${t.confidence}%</td><td><button class="view" onclick="selectTrain('${t.train_no}')">View</button></td></tr>`});
 $("#stats").innerHTML=`<div class="stat"><label>TRAINS MONITORED</label><b>${data.length}</b><small>● live feed coverage</small></div><div class="stat"><label>ON TIME / LOW DELAY</label><b>${data.filter(x=>x.delay<10).length}</b><small>Dynamic status</small></div><div class="stat"><label>ACTIVE DELAYS</label><b>${delayed}</b><small>Needs attention</small></div><div class="stat"><label>AVG FORECAST CONF.</label><b>${data.length?Math.round(avg/data.length):0}%</b><small>Model confidence</small></div>`;
 $("#updated").textContent="Updated "+new Date().toLocaleTimeString();
 if(selected) selectTrain(selected);
}
function etaFromDelay(d){let now=new Date();now=new Date(now.getTime()+Math.max(0,d)*60000);return now.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",hour12:false})}
async function selectTrain(no){
 selected=no; const [t,st,ev]=await Promise.all([api(`/api/trains/${no}`),api(`/api/trains/${no}/stations`),api(`/api/trains/${no}/events`)]);
 $("#detailTitle").textContent=`${t.train_no} · ${t.name}`; $("#detailStatus").outerHTML=badge(t.status);
 let stations=st.map(s=>`<div class="station"><span><b>${s.station}</b><br><small>${s.scheduled} scheduled</small></span><span style="text-align:right"><b>${s.eta}</b><br><small>+${s.predicted_delay}m · ${s.confidence}%</small></span></div>`).join("");
 let events=ev.length?ev.map(e=>`<div class="event"><b>${e.event_type} · +${e.impact} min</b><small>${e.message}<br>${e.created}</small></div>`).join(""):`<div class="empty">No recent events</div>`;
 $("#detailBody").innerHTML=`<div class="bigeta">${t.next_eta||etaFromDelay(t.delay)}</div><div style="font-size:10px;color:#667085">Next-station ETA · live model confidence ${t.confidence}%</div><div class="kv"><div><small>Current speed</small><b>${t.speed} km/h</b></div><div><small>Current delay</small><b>${t.delay} min</b></div><div><small>Next station</small><b>${t.next_station}</b></div><div><small>Platform</small><b>${t.platform||"TBD"}</b></div><div><small>Position</small><b>${Number(t.lat).toFixed(3)}, ${Number(t.lon).toFixed(3)}</b></div><div><small>Updated</small><b>${t.updated.slice(11,19)}</b></div></div><button class="btn" onclick="simulate('${t.train_no}')">⚡ Simulate live update</button><div class="section"><h3>Upcoming ETA Forecast</h3>${stations}</div><div class="section"><h3>Delay / Event Feed</h3>${events}</div>`;
}
async function simulate(no){await api(`/api/trains/${no}/simulate`,{method:"POST"});await loadTrains();await selectTrain(no)}
setInterval(()=>{clock();},1000); setInterval(()=>loadTrains(true),10000);
$("#search").addEventListener("keydown",e=>{if(e.key==="Enter")loadTrains(false)});
clock(); loadTrains(true);
