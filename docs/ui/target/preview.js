/* Standalone design prototype. All capabilities and conversation content are synthetic. */
const languages = {
  de: {name: 'German', native: 'Deutsch'}, zh: {name: 'Mandarin Chinese', native: '普通话'},
  en: {name: 'English', native: 'English'}, es: {name: 'Spanish', native: 'Español'},
  fr: {name: 'French', native: 'Français'}
};
const examples = {
  de: ['Guten Morgen. Wann fährt der nächste Zug nach Berlin?', 'Der nächste Zug fährt um zehn Uhr.'],
  zh: ['早上好。下一班去柏林的火车几点出发？', '下一班火车十点出发。'],
  en: ['Good morning. When is the next train to Berlin?', 'The next train leaves at ten.'],
  es: ['Buenos días. ¿Cuándo sale el próximo tren a Berlín?', 'El próximo tren sale a las diez.'],
  fr: ['Bonjour. À quelle heure part le prochain train pour Berlin ?', 'Le prochain train part à dix heures.']
};
let state = 'conversation', first = 'de', second = 'zh', turns = true, setupStep = 0;
let bridgeConfigured = false, tested = new Set();
let textDraft = examples.de[0], textResult = true;
const $ = selector => document.querySelector(selector);
const name = code => languages[code].name;
const pairReady = () => ['de-zh','zh-de','en-es','es-en'].includes(`${first}-${second}`);
const voicesReady = () => pairReady() && ![first,second].includes('es');
const options = selected => Object.entries(languages).map(([code, value]) => `<option value="${code}" ${code === selected ? 'selected' : ''}>${value.name} · ${value.native}</option>`).join('');
function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => $('#toast').hidden = true, 4500); }
function view() { return state.startsWith('bridge') ? 'bridge' : state.startsWith('speech-text') ? 'speech-text' : state.startsWith('text') ? 'text' : ['languages', 'setup'].includes(state) ? state : 'conversation'; }
function pair() {
  if (['text','speech-text'].includes(view())) return `<div class="pair-bar"><label class="field">Source language<select id="language-a">${options(first)}</select></label><button class="swap" data-action="swap" aria-label="Swap selected languages">⇄</button><label class="field">Target language<select id="language-b">${options(second)}</select></label><div class="pair-note"><strong>${view()==='text'?'One direction · text in, translation out':'One direction · speech in, text out'}</strong>${view()==='text'?'No microphone or speech-recognition model required.':'No spoken output. Only the source language is recognized.'}</div></div>`;
  return `<div class="pair-bar"><label class="field">${view() === 'bridge' ? 'Your language' : 'Language A'}<select id="language-a">${options(first)}</select></label><button class="swap" data-action="swap" aria-label="Swap selected languages">⇄</button><label class="field">${view() === 'bridge' ? 'Partner’s language' : 'Language B'}<select id="language-b">${options(second)}</select></label><div class="pair-note"><strong>${view() === 'bridge' ? 'Fixed direction for each audio lane' : 'Automatic · between these two languages'}</strong>${view() === 'bridge' ? 'Change the pair only while stopped.' : 'Other languages prompt a choice; no silent guessing.'}</div></div>`;
}
function heading(eyebrow, title, subtitle, actions = '') {return `<div class="heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`;}
function capabilityWarning() {
  if (first === second) return '<div class="banner error"><div><strong>Choose two different languages</strong><p>A conversation needs a source and a target language.</p></div></div>';
  if (!pairReady()) return '<div class="banner"><div><strong>This language pair is not ready</strong><p>Preview scenario: a required translation direction for this pair is unavailable. Language recognition alone is not enough.</p></div><button data-view="languages">Review language packs</button></div>';
  return '';
}
function conversation() {
  const empty = state === 'loading' || !turns;
  const status = {conversation:['Listening','Speak in short turns. Pause when you finish.'],ready:['Ready to start','Your microphone is off.'],speaking:['Speaking · microphone paused','Please wait until listening resumes.'],translating:['Translating','Your turn is being processed locally.'],loading:['Loading offline models','Preparing speech recognition and translation…'],error:['Microphone disconnected','Recording stopped. Reconnect or choose a device.']}[state];
  const blocked = ['loading','error'].includes(state) || !pairReady();
  return heading('Conversation interpreting','A conversation, in both languages','Turn-by-turn interpreting after a pause. Everything stays on your device.', '<button data-action="new">New conversation</button><button data-action="export" '+(empty?'disabled':'')+'>Export transcript</button>') + pair() + capabilityWarning() +
  (state === 'error' ? '<div class="banner error" role="alert"><div><strong>Reconnect your microphone to continue</strong><p>The conversation is preserved. Recording will not restart automatically.</p></div><button data-view="setup">Choose microphone</button></div>' : '') +
  `<section class="conversation" aria-label="Conversation transcript"><div class="section-bar"><span>Conversation ${empty?'':'· 2 turns'}</span><span>Original + translation</span></div><div class="turns">` +
  (empty ? `<div class="empty"><div class="symbol" aria-hidden="true">↔</div><h2>${state === 'loading' ? 'Preparing your languages' : 'Make room for understanding'}</h2><p>${state === 'loading' ? 'The first start may take longer. Your microphone is still off.' : 'Press Start, speak in either selected language, then pause for the translation.'}</p></div>` : [0,1].map(i=>{const source=i?second:first,target=i?first:second;return `<article class="turn"><div class="turn-meta"><strong>${name(source)}</strong><span>10:4${i+2} · Turn ${i+1}</span></div><div><p class="original" lang="${source}" dir="auto">${examples[source][i]}</p><div class="translation" lang="${target}" dir="auto"><small lang="en">${name(target)} translation</small>${examples[target][i]}</div></div><div class="turn-actions"><button data-action="copy" data-turn="${i}" aria-label="Copy turn ${i+1}">Copy</button><button data-action="replay" ${target==='es'?'disabled title="Spanish voice not installed"':''} aria-label="Replay turn ${i+1} translation">Replay</button></div></article>`;}).join('')) +
  `</div><div class="session-controls"><div class="status" role="status"><div class="meter ${state!=='conversation'?'paused':''}" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><div><strong>${status[0]}</strong><small>${status[1]}</small></div></div><div class="actions"><button data-action="voice">Voice output: ${voicesReady()?'on':'unavailable'}</button>${['ready','loading','error'].includes(state)?`<button class="primary" data-action="start" ${blocked?'disabled':''}>Start conversation <span class="key">F8</span></button>`:'<button class="danger" data-action="stop">Stop session <span class="key">F9</span></button>'}</div></div></section><div class="device-strip"><span>Microphone: USB headset · Output: Headphones <button class="text-button" data-view="setup">Change devices</button></span><span>${empty?'Models and devices checked before start':'Last turn · 1.8 s processing (sample)'}</span></div>`;
}
function bridge() {
  const live = state !== 'bridge', degraded = state === 'bridge-error';
  return heading('Call translation','Call Bridge','Your language to the call. Your partner’s language to you.','<span class="badge warn">Experimental · device acceptance required</span>') + pair() + capabilityWarning() +
  `<div class="banner ${degraded?'error':''}"><div><strong>${degraded?'Partner audio disconnected · incoming lane muted':live?'Both routes are active · example state':'Set up and test both audio routes'}</strong><p>${degraded?'Your outgoing lane remains active. No fallback device will be selected.':live?'Each lane keeps its configured language direction throughout the call.':'Two virtual audio cables are required. Keep your physical microphone out of the call app’s microphone selection.'}</p></div>${degraded?'<button data-action="recover">Review incoming route</button>':''}</div>` +
  `<div class="two-col">${[0,1].map(i=>{const failed=degraded&&i, source=i?second:first, target=i?first:second;return `<section class="panel"><div class="route-head"><div><h2>${i?'Your partner → you':'You → your partner'}</h2><div class="direction-title">${name(source)} → ${name(target)}</div></div><span class="badge ${failed?'bad':!live?'warn':''}">${failed?'Muted':live?'Listening':tested.has(i)?'Test confirmed':'Setup required'}</span></div><div class="route-step"><label class="field">${i?'Audio from the call app':'Your microphone'}<select class="route-select" ${live?'disabled':''}><option value="">Choose a device…</option><option value="device" ${live||bridgeConfigured?'selected':''}>${i?'Virtual cable B · receive from call':'USB headset · microphone'}</option></select></label><p class="route-arrow">${name(source)} speech → ${name(target)} translation</p></div><div class="route-step"><label class="field">${i?'Your headphones':'Translated audio to the call app'}<select class="route-select" ${live?'disabled':''}><option value="">Choose a device…</option><option value="device" ${live||bridgeConfigured?'selected':''}>${i?'Headphones · local playback':'Virtual cable A · send to call'}</option></select></label></div><div class="route-bottom"><small>${failed?'No incoming signal':live?'Input level · signal present':tested.has(i)?'Expected destination confirmed (demo)':'Test with a consenting partner'}</small><button data-action="route-test" data-lane="${i}" ${live?'disabled':''}>Test this route</button></div></section>`;}).join('')}</div><div class="help"><strong>In your call app</strong><br>Microphone: virtual cable A’s recording side. Speakers: virtual cable B’s playback side. Names such as “Input” and “Output” are shown with their destination in the setup guide.</div><div class="bridge-footer"><small>${live?'Changes are locked while a session is active. Stop both lanes before changing languages or devices.':'Start becomes available after both routes, models and voices pass validation. A route test is not a live-call acceptance certificate.'}</small>${live?'<button class="danger" data-action="bridge-stop">Stop both lanes <span class="key">F9</span></button>':`<button class="primary" data-action="bridge-start" ${!bridgeConfigured||tested.size!==2||!voicesReady()?'disabled':''}>Start Call Bridge</button>`}</div>`;
}
function packs() {
  const rows=[['de','Recognition ready','de → zh · ready','German voice ready','Details'],['zh','Recognition ready','zh → de · ready','Mandarin voice ready','Details'],['en','Recognition ready','en ↔ es · sample available','English voice ready','Details'],['es','Recognition ready','es ↔ en · sample available','Voice not installed','Review pack'],['fr','Planned / unvalidated','No validated direction','No validated voice','View requirements']];
  return heading('Offline capabilities','Language packs','Readiness belongs to each direction and voice, not just a language name.') + '<div class="banner"><div><strong>Illustrative catalog — not your installed models</strong><p>German, Mandarin, English, Spanish and French demonstrate future capability states. This preview adds no language support.</p></div></div><section class="panel"><div class="table-head"><span>Language</span><span>Recognition & translation</span><span>Spoken output</span><span>Action</span></div>' + rows.map(([code,stt,mt,voice,action])=>`<div class="pack"><div><strong>${name(code)}</strong><small class="native">${languages[code].native}</small></div><div class="capability">${stt}<small>${mt}</small></div><div class="capability ${voice.includes('not')||voice.includes('No ')?'language-warning':''}">${voice}<small>${code==='es'?'Text translation can still work':'Validated per model and locale'}</small></div><button data-action="pack" data-language="${code}">${action}</button></div>`).join('') + '</section><p class="notice">Before any download: show source, version, size, disk requirement, license and integrity check. Installing a pack requires an explicit action and an internet connection. Conversation processing remains local.</p>';
}
function setup() {
  const steps=['Choose languages','Check audio','Review readiness'];
  return heading('Settings & first-run setup','Ready before the first word','Three short checks. You can change these settings later.') + `<div class="setup"><ol class="steps">${steps.map((s,i)=>`<li class="${i===setupStep?'current':''}">${i+1}. ${s}</li>`).join('')}</ol><section class="panel"><h2>${steps[setupStep]}</h2>` +
  (setupStep===0?`<p>Select the languages spoken in this conversation. Interface language is a separate setting.</p><div class="settings-fields"><label class="field">Language A<select id="language-a">${options(first)}</select></label><label class="field">Language B<select id="language-b">${options(second)}</select></label></div>${capabilityWarning()}<div class="help">Automatic detection is limited to this pair. If recognition is uncertain or another language is detected, the app asks you to choose instead of translating into an arbitrary language.</div><button data-view="languages">Review model and voice readiness</button>`:
  setupStep===1?'<p>Generic devices below illustrate the setup flow.</p><div class="settings-fields"><label class="field">Microphone<select><option>USB headset · microphone</option></select></label><label class="field">Playback device<select><option>Headphones · local playback</option></select></label></div><div class="actions"><button data-action="mic-test">Test microphone</button><button data-action="speaker-test">Play test sound</button><button data-action="refresh">Refresh devices</button></div><div class="help">A disconnected or ambiguous device requires your attention. Call Bridge never switches silently to Windows default audio.</div>':`<p>${name(first)} ↔ ${name(second)}</p><div class="help"><strong>Example readiness summary</strong><br>✓ Speech recognition for both selected languages<br>✓ Both translation directions<br>✓ Microphone and headphones selected<br>Voice output is optional for in-person text translation.</div><label class="check"><input type="checkbox" ${voicesReady()?'checked':'disabled'}> Enable spoken translations when both voices are ready</label><p class="muted">No transcript is saved automatically. Export only when you choose.</p>`) + `<div class="bridge-footer"><button data-action="setup-back" ${setupStep===0?'disabled':''}>Back</button><button class="primary" data-action="setup-next" ${!pairReady()?'disabled':''}>${setupStep===2?'Open conversation':'Continue'}</button></div></section></div>`;
}
function escapeText(value) {return value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
function textTranslation() {
  const speaking = state === 'text-speaking', voiceReady = pairReady() && second !== 'es';
  return heading('Text translation','Write it. Translate it. Say it.','Translate locally, then read or play the translated text.') + pair() + capabilityWarning() +
    `<div class="translation-workspace"><section class="editor-panel"><div class="section-bar"><label for="source-draft">${name(first)} · Your text</label><span>Editable source</span></div><textarea id="source-draft" lang="${first}" dir="auto" placeholder="Type or paste text to translate…" ${speaking?'disabled':''}>${escapeText(textDraft)}</textarea><div class="editor-actions"><small>No microphone access</small><button class="primary" data-action="translate-text" ${!pairReady()||speaking||!textDraft.trim()?'disabled':''}>Translate</button></div></section><section class="editor-panel"><div class="section-bar"><span>${name(second)} · Translation</span><span>Always visible when speaking</span></div><div class="translated-draft" lang="${second}" dir="auto">${textResult&&pairReady()?examples[second][0]:'Your translation will appear here.'}</div><div class="editor-actions"><button data-action="copy-text" ${!textResult||!pairReady()?'disabled':''}>Copy translation</button><button data-action="${speaking?'stop-text-speech':'speak-text'}" ${!textResult||!voiceReady?'disabled':''}>${speaking?'Stop playback':'Play translation'}</button></div></section></div><div class="session-controls text-status"><div class="status" role="status"><div class="meter paused" aria-hidden="true"><i></i><i></i><i></i></div><div><strong>${speaking?'Speaking the translation':!voiceReady?'Text available · target voice unavailable':'Text translation ready'}</strong><small>${speaking?'The translated text remains visible. Your microphone stays off.':!voiceReady?'Install the target-language voice to play this translation.':'Playback is optional and starts only when you choose Play translation.'}</small></div></div><span class="badge">Microphone off</span></div><p class="notice">Preview: Translate works with the supplied example sentence only. Other input is preserved, but no translation engine runs in this mockup.</p>`;
}
function speechToText() {
  const listening = state === 'speech-text';
  return heading('Speech-to-translated-text','Listen in one language. Read in another.','A fixed source and target. Translation appears after each speech pause.','<button data-action="export">Export transcript</button>') + pair() + capabilityWarning() +
    `<section class="conversation"><div class="section-bar"><span>Recognized speech + translated text</span><span>No voice output</span></div><div class="turns">${[0,1].map((i)=>`<article class="turn"><div class="turn-meta"><strong>${name(first)}</strong><span>Segment ${i+1}</span></div><div><p class="original" lang="${first}" dir="auto">${examples[first][i]}</p><div class="translation" lang="${second}" dir="auto"><small lang="en">${name(second)} translation</small>${examples[second][i]}</div></div></article>`).join('')}</div><div class="session-controls"><div class="status" role="status"><div class="meter ${listening?'':'paused'}" aria-hidden="true"><i></i><i></i><i></i><i></i></div><div><strong>${listening?'Listening to '+name(first):'Stopped · transcript preserved'}</strong><small>${listening?'Translating into '+name(second)+'. Speakers remain silent.':'Microphone off. Resume when you are ready.'}</small></div></div><button class="${listening?'danger':'primary'}" data-action="${listening?'stop-speech-text':'start-speech-text'}" ${!pairReady()?'disabled':''}>${listening?'Stop listening':'Start listening'} <span class="key">${listening?'F9':'F8'}</span></button></div></section><div class="device-strip"><span>Microphone: USB headset <button data-view="setup">Change microphone</button></span><span>No voice model or speaker device required</span></div>`;
}
function render() {
  $('#content').dataset.surface = view();
  document.querySelectorAll('[data-view]').forEach(el=>el.removeAttribute('aria-current'));
  document.querySelector(`nav [data-view="${view()}"]`).setAttribute('aria-current','page');
  $('#scenario').value=state;
  $('#content').innerHTML = view()==='text'?textTranslation():view()==='speech-text'?speechToText():view()==='bridge'?bridge():view()==='languages'?packs():view()==='setup'?setup():conversation();
  const locked = ['conversation','speaking','translating','bridge-live','bridge-error','text-speaking','speech-text'].includes(state);
  document.querySelectorAll('#language-a,#language-b,[data-action="swap"]').forEach(el=>el.disabled=locked);
}
function navigate(next) {clearTimeout(window.toastTimer); $('#toast').hidden=true; state=next;location.hash=next;render();}
$('#scenario').addEventListener('change', e=>{ if(e.target.value==='ready')turns=false; else if(['conversation','speaking','translating'].includes(e.target.value))turns=true; if(e.target.value.startsWith('text')){textDraft=examples[first][0];textResult=true;} navigate(e.target.value); });
document.addEventListener('change', e=>{
  if(e.target.id==='language-a') first=e.target.value;
  else if(e.target.id==='language-b') second=e.target.value;
  else if(e.target.matches('.route-select')) {bridgeConfigured=[...document.querySelectorAll('.route-select')].every(s=>s.value);tested.clear(); const button=$('[data-action="bridge-start"]');button.disabled=true;return;}
  else return;
  if(view()==='text'){textDraft=examples[first][0];textResult=false;}
  tested.clear();render();
});
document.addEventListener('input', e=>{
  if(e.target.id!=='source-draft')return;
  textDraft=e.target.value;textResult=false;
  $('.translated-draft').textContent='Source changed. Translate again to update the result.';
  $('[data-action="speak-text"]').disabled=true;
  $('[data-action="copy-text"]').disabled=true;
  $('[data-action="translate-text"]').disabled=!textDraft.trim()||!pairReady();
});
document.addEventListener('click', async e=>{
  const button=e.target.closest('button'); if(!button||button.disabled)return;
  if(button.dataset.view){navigate(button.dataset.view==='conversation'?'ready':button.dataset.view==='speech-text'?'speech-text-ready':button.dataset.view);return;}
  switch(button.dataset.action){
    case 'swap': [first,second]=[second,first];if(view()==='text'){textDraft=examples[first][0];textResult=false;}tested.clear();render();break;
    case 'translate-text':if(textDraft.trim()!==examples[first][0]){notify('Preview only: arbitrary text is not translated. Use the supplied sample or keep your draft for design review.');return;}textResult=true;render();break;
    case 'speak-text':navigate('text-speaking');break;
    case 'stop-text-speech':navigate('text');break;
    case 'start-speech-text':navigate('speech-text');break;
    case 'stop-speech-text':navigate('speech-text-ready');break;
    case 'copy-text':try{await navigator.clipboard.writeText(examples[second][0]);notify('Example translation copied.');}catch{notify('Clipboard unavailable.');}break;
    case 'start':turns=true;navigate('conversation');break;
    case 'stop':navigate('ready');break;
    case 'new':if(confirm('Clear the example conversation? Unsaved turns will be removed.')){turns=false;navigate('ready');}break;
    case 'export':notify('Preview: the app would open Save transcript. Nothing has been saved.');break;
    case 'copy': {const i=Number(button.dataset.turn), source=i?second:first,target=i?first:second;try{await navigator.clipboard.writeText(`${name(source)}: ${examples[source][i]}\n${name(target)}: ${examples[target][i]}`);notify('Example turn copied.');}catch{notify('Clipboard unavailable in this preview.');}break;}
    case 'replay':navigate('speaking');notify('Preview speaking state. No sound is played.');break;
    case 'voice':notify('Preview: voice preference would be stored per profile; missing voices are explained before enabling.');break;
    case 'route-test': if(!bridgeConfigured){notify('Choose all four endpoints before the route test.');return;}tested.add(Number(button.dataset.lane));render();notify('Simulated destination confirmation. No audio route was tested.');break;
    case 'bridge-start':navigate('bridge-live');break;
    case 'bridge-stop':navigate('bridge');break;
    case 'recover':navigate('bridge');bridgeConfigured=false;tested.clear();render();break;
    case 'setup-back':setupStep=Math.max(0,setupStep-1);render();break;
    case 'setup-next':if(setupStep===2)navigate('ready');else{setupStep++;render();}break;
    case 'pack':notify(`Preview: ${name(button.dataset.language)} model source, license, size, direction support and verification details. No download starts.`);break;
    default:notify('Preview only: no device access, downloads or sound.');
  }
});
document.addEventListener('keydown', e=>{if(e.key==='F9'){e.preventDefault();navigate(view()==='text'?'text':view()==='speech-text'?'speech-text-ready':view()==='bridge'?'bridge':'ready');}if(e.key==='F8'&&view()==='conversation'&&state==='ready'&&pairReady()){e.preventDefault();turns=true;navigate('conversation');}else if(e.key==='F8'&&state==='speech-text-ready'&&pairReady()){e.preventDefault();navigate('speech-text');}});
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if([...$('#scenario').options].some(o=>o.value===next)){state=next;render();}});
if([...$('#scenario').options].some(o=>o.value===location.hash.slice(1)))state=location.hash.slice(1);
if(state==='ready')turns=false;
render();
