'use strict';
// ═══════════════════════════════════════════════════════════════════════════
// LAMMPS Dashboard — browser client
// ═══════════════════════════════════════════════════════════════════════════

// ── Socket.IO ──────────────────────────────────────────────────────────────
const socket = io();

// ── Global state ──────────────────────────────────────────────────────────
let editor = null;
let thermoData = null;
let thermoChart = null;
let sshConnected = false;
let currentFilePath = '';
let currentFileRemote = false;
let currentDir = '';
let aiPartial = '';
let aiPending = false;
let aiStreaming = false;
let selectedProfile = null;
let hpcModules = [];

// ═══════════════════════════════════════════════════════════════════════════
// Tabs
// ═══════════════════════════════════════════════════════════════════════════
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.remove('hidden');
    if (btn.dataset.tab === 'plots' && thermoData) populatePlotSelectors(thermoData);
    if (btn.dataset.tab === 'ai') refreshAiModels();
    if (btn.dataset.tab === 'ssh') loadSshProfiles();
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// CodeMirror + LAMMPS mode
// ═══════════════════════════════════════════════════════════════════════════
CodeMirror.defineSimpleMode('lammps', {
  start: [
    { regex: /#.*/, token: 'comment' },
    { regex: /\$\{[^}]+\}|v_\w+|c_\w+|f_\w+/, token: 'variable-2' },
    { regex: /(?:units|atom_style|boundary|dimension|pair_style|pair_coeff|bond_style|bond_coeff|angle_style|angle_coeff|dihedral_style|dihedral_coeff|improper_style|improper_coeff|kspace_style|kspace_modify|neighbor|neigh_modify|atom_modify|comm_modify|fix|unfix|compute|uncompute|dump|undump|group|region|create_box|create_atoms|read_data|read_restart|write_data|write_restart|minimize|run|timestep|thermo|thermo_style|thermo_modify|velocity|reset_timestep|log|echo|print|variable|label|jump|if|then|else|include|shell|package|suffix|newton|processors|clear)\b/, token: 'keyword' },
    { regex: /(?:lj\/cut|lj\/long|coul\/long|coul\/cut|reax\/c|tersoff|eam|eam\/alloy|sw|meam|airebo|table|morse|buck|born|yukawa|dpd|hybrid|overlay)\b/, token: 'atom' },
    { regex: /(?:nve|nvt|npt|langevin|berendsen|rescale|minimize|rigid|shake|spring|indent|wall|deform|ave\/time|ave\/atom|ave\/chunk|rerun|temp|press|pe|ke|etotal|lx|ly|lz|vol|density|pxx|pyy|pzz|pxy|pxz|pyz|enthalpy|step|cpu|elapsed|elaplong|dt|time|atoms|bonds|angles|temp\/com|press\/chunk)\b/, token: 'string' },
    { regex: /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/, token: 'number' },
    { regex: /[=<>!]+/, token: 'operator' },
  ],
  meta: { lineComment: '#' }
});

function initEditor() {
  editor = CodeMirror(document.getElementById('editor-wrap'), {
    mode: 'lammps',
    theme: 'dracula',
    lineNumbers: true,
    matchBrackets: true,
    indentWithTabs: false,
    tabSize: 4,
    lineWrapping: false,
    value: '# Open a file from the tree to start editing\n',
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// File browser
// ═══════════════════════════════════════════════════════════════════════════
async function loadDir(path, remote = false) {
  currentDir = path;
  document.getElementById('path-bar').value =
    remote ? `[SSH] ${path}` : path;
  const url = remote ? `/api/ssh/files?path=${encodeURIComponent(path)}`
                     : `/api/files?dir=${encodeURIComponent(path)}`;
  try {
    const r = await fetch(url);
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    renderTree(d.entries, d.parent, remote);
  } catch (e) { alert('Error: ' + e); }
}

function renderTree(entries, parent, remote) {
  const tree = document.getElementById('file-tree');
  tree.innerHTML = '';
  if (parent !== null) {
    const up = makeTreeItem('..', '↑', 'tree-dir', () => loadDir(parent, remote));
    tree.appendChild(up);
  }
  entries.forEach(e => {
    const icon = e.type === 'dir' ? '📂' : fileIcon(e.name);
    const cls  = e.type === 'dir' ? 'tree-dir' : 'tree-file';
    const item = makeTreeItem(e.name, icon, cls, () => {
      if (e.type === 'dir') {
        loadDir(e.path, remote);
      } else {
        openFile(e.path, remote);
        tree.querySelectorAll('.tree-item').forEach(i => i.classList.remove('selected'));
        item.classList.add('selected');
      }
    });
    tree.appendChild(item);
  });
}

function makeTreeItem(name, icon, cls, onClick) {
  const div  = document.createElement('div');
  div.className = `tree-item ${cls}`;
  div.innerHTML = `<span class="icon">${icon}</span><span class="name">${escHtml(name)}</span>`;
  div.addEventListener('click', onClick);
  return div;
}

function fileIcon(name) {
  if (/\.py$/i.test(name))   return '🐍';
  if (/\.(sh|bash)$/i.test(name)) return '⚙';
  if (/log/i.test(name))     return '📋';
  if (/\.(png|jpg|gif)$/i.test(name)) return '🖼';
  return '📄';
}

async function openFile(path, remote = false) {
  const url = remote ? `/api/ssh/file?path=${encodeURIComponent(path)}`
                     : `/api/file?path=${encodeURIComponent(path)}`;
  try {
    const r = await fetch(url);
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    editor.setValue(d.content);
    currentFilePath = path;
    currentFileRemote = remote;
    document.getElementById('editor-filename').textContent =
      (remote ? '[SSH] ' : '') + path;
    // Auto-set run fields from file path
    const dir = path.substring(0, path.lastIndexOf('/')) || '/';
    const base = path.substring(path.lastIndexOf('/') + 1);
    document.getElementById('run-dir').value = dir;
    document.getElementById('run-input').value = base;
    document.getElementById('plot-log-path').value = dir + '/log.lammps';
  } catch (e) { alert('Error: ' + e); }
}

async function saveFile() {
  if (!currentFilePath) { alert('No file open'); return; }
  const content = editor.getValue();
  const url = currentFileRemote ? '/api/ssh/file' : '/api/file';
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: currentFilePath, content }),
  });
  const d = await r.json();
  if (d.error) alert('Save failed: ' + d.error);
}

// File tab controls
document.getElementById('btn-go').addEventListener('click', () => {
  let p = document.getElementById('path-bar').value.trim();
  const remote = p.startsWith('[SSH]');
  if (remote) p = p.replace(/^\[SSH\]\s*/, '');
  loadDir(p, remote);
});
document.getElementById('path-bar').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('btn-go').click();
});
document.getElementById('btn-up').addEventListener('click', () => {
  const p = currentDir;
  const parent = p === '/' ? '/' : p.substring(0, p.lastIndexOf('/')) || '/';
  loadDir(parent, sshConnected && document.getElementById('path-bar').value.startsWith('[SSH]'));
});
document.getElementById('btn-save').addEventListener('click', saveFile);
document.getElementById('btn-save-as').addEventListener('click', async () => {
  const newPath = prompt('Save as:', currentFilePath);
  if (!newPath) return;
  currentFilePath = newPath;
  currentFileRemote = sshConnected && document.getElementById('path-bar').value.startsWith('[SSH]');
  document.getElementById('editor-filename').textContent =
    (currentFileRemote ? '[SSH] ' : '') + newPath;
  await saveFile();
});
document.getElementById('btn-new-file').addEventListener('click', async () => {
  const name = prompt('New file name:');
  if (!name) return;
  const path = currentDir.replace(/\/$/, '') + '/' + name;
  const url = sshConnected ? '/api/ssh/file' : '/api/file';
  await fetch(url, { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path, content: '' }) });
  await loadDir(currentDir, sshConnected);
});
document.getElementById('btn-new-dir').addEventListener('click', async () => {
  const name = prompt('New folder name:');
  if (!name) return;
  const path = currentDir.replace(/\/$/, '') + '/' + name;
  await fetch('/api/mkdir', { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path }) });
  await loadDir(currentDir, sshConnected);
});

// Pane resize
(function() {
  const handle = document.getElementById('pane-resize');
  const treePanel = document.getElementById('tree-panel');
  let dragging = false, startX = 0, startW = 0;
  handle.addEventListener('mousedown', e => {
    dragging = true; startX = e.clientX; startW = treePanel.offsetWidth;
    document.body.style.cursor = 'col-resize';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const w = Math.max(150, Math.min(600, startW + e.clientX - startX));
    treePanel.style.width = w + 'px';
  });
  document.addEventListener('mouseup', () => {
    dragging = false; document.body.style.cursor = '';
  });
})();

// ═══════════════════════════════════════════════════════════════════════════
// Run tab
// ═══════════════════════════════════════════════════════════════════════════
const logView = document.getElementById('log-view');

function appendLog(text, cls = '') {
  const div = document.createElement('div');
  div.className = 'log-line' + (cls ? ' ' + cls : '');
  div.textContent = text;
  logView.appendChild(div);
  if (document.getElementById('log-autoscroll').checked) {
    logView.scrollTop = logView.scrollHeight;
  }
}

document.getElementById('btn-run').addEventListener('click', async () => {
  const inp    = document.getElementById('run-input').value.trim();
  const dir    = document.getElementById('run-dir').value.trim();
  const np     = document.getElementById('run-np').value;
  const bin    = document.getElementById('run-bin').value.trim();
  const extra  = document.getElementById('run-extra').value.trim();
  const remote = document.getElementById('run-remote').checked;
  if (!inp) { alert('Enter input file'); return; }
  const r = await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ input_file: inp, working_dir: dir, np, lmp_bin: bin, extra_args: extra, remote }),
  });
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  setRunning(true);
  appendLog(`▶ Starting: mpirun -np ${np} ${bin} -in ${inp}`, 'log-ok');
});

document.getElementById('btn-stop').addEventListener('click', async () => {
  await fetch('/api/stop', { method: 'POST' });
});

document.getElementById('btn-parse-log').addEventListener('click', async () => {
  const path   = document.getElementById('plot-log-path').value ||
                 document.getElementById('run-dir').value + '/log.lammps';
  const remote = sshConnected && document.getElementById('run-remote').checked;
  const r = await fetch(`/api/parse_log?path=${encodeURIComponent(path)}&remote=${remote}`);
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  if (!d.headers || d.headers.length === 0) { alert('No thermo data found in log.'); return; }
  thermoData = d;
  populatePlotSelectors(d);
  document.querySelector('[data-tab=plots]').click();
});

document.getElementById('btn-clear-log').addEventListener('click', () => {
  logView.innerHTML = '';
});

document.getElementById('btn-browse-input').addEventListener('click', () => {
  document.querySelector('[data-tab=files]').click();
});

function setRunning(running) {
  document.getElementById('btn-run').disabled  = running;
  document.getElementById('btn-stop').disabled = !running;
  document.getElementById('run-status').textContent = running ? '● Running…' : 'Idle';
  document.getElementById('run-status').style.color = running ? 'var(--green)' : 'var(--fg2)';
}

// Socket.IO events
socket.on('log_line', d => appendLog(d.line,
  /error|failed/i.test(d.line) ? 'log-err' :
  /warning/i.test(d.line) ? 'log-warn' : ''));

socket.on('status', d => {
  setRunning(d.running);
  if (!d.running) {
    const rc = d.returncode;
    appendLog(`⬛ Simulation ended — exit code: ${rc}`, rc === 0 ? 'log-ok' : 'log-err');
  }
});

socket.on('thermo_ready', d => {
  thermoData = d;
  populatePlotSelectors(d);
  appendLog('📊 Thermo data parsed — click the Plots tab to view.', 'log-ok');
});

// ═══════════════════════════════════════════════════════════════════════════
// Plots tab
// ═══════════════════════════════════════════════════════════════════════════
function populatePlotSelectors(data) {
  const headers = data.headers;
  const selX = document.getElementById('plot-x');
  const selY = document.getElementById('plot-y');
  selX.innerHTML = headers.map(h => `<option value="${h}">${h}</option>`).join('');
  selY.innerHTML = headers.filter(h => h !== 'Step').map(h =>
    `<option value="${h}" ${['Temp','PotEng','TotEng','Press'].includes(h) ? 'selected' : ''}>${h}</option>`
  ).join('');
}

document.getElementById('btn-plot').addEventListener('click', () => {
  if (!thermoData) { alert('No data. Run a simulation or load a log file.'); return; }
  const xKey = document.getElementById('plot-x').value;
  const yKeys = [...document.getElementById('plot-y').selectedOptions].map(o => o.value);
  if (!yKeys.length) { alert('Select at least one Y column.'); return; }
  renderChart(thermoData, xKey, yKeys);
});

document.getElementById('btn-load-log').addEventListener('click', async () => {
  const path   = document.getElementById('plot-log-path').value.trim() || 'log.lammps';
  const remote = sshConnected;
  const r = await fetch(`/api/parse_log?path=${encodeURIComponent(path)}&remote=${remote}`);
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  if (!d.headers || !d.headers.length) { alert('No thermo data found.'); return; }
  thermoData = d;
  populatePlotSelectors(d);
  document.getElementById('no-plot-msg').style.display = 'none';
});

const COLORS = ['#4fc3f7','#81c784','#ffd54f','#ef5350','#ce93d8','#80cbc4','#ffb74d','#e57373'];

function renderChart(data, xKey, yKeys) {
  const xVals = data.data[xKey] || [];
  document.getElementById('no-plot-msg').style.display = 'none';

  const datasets = yKeys.map((k, i) => ({
    label: k,
    data: (data.data[k] || []).map((v, idx) => ({ x: xVals[idx], y: v })),
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: COLORS[i % COLORS.length] + '22',
    borderWidth: 1.5,
    pointRadius: xVals.length > 500 ? 0 : 2,
    tension: 0.1,
  }));

  if (thermoChart) thermoChart.destroy();
  thermoChart = new Chart(document.getElementById('thermo-chart'), {
    type: 'line',
    data: { datasets },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#d4d4d4', font: { size: 11 } } },
      },
      scales: {
        x: {
          type: 'linear',
          title: { display: true, text: xKey, color: '#8a9ab0' },
          ticks: { color: '#8a9ab0' },
          grid:  { color: '#2d3139' },
        },
        y: {
          title: { display: true, text: yKeys.join(', '), color: '#8a9ab0' },
          ticks: { color: '#8a9ab0' },
          grid:  { color: '#2d3139' },
        },
      },
    },
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SSH tab
// ═══════════════════════════════════════════════════════════════════════════
async function loadSshProfiles() {
  const r = await fetch('/api/ssh/profiles');
  const d = await r.json();
  const list = document.getElementById('profile-list');
  list.innerHTML = '';
  (d.profiles || []).forEach(p => {
    const item = document.createElement('div');
    item.className = 'profile-item' + (selectedProfile === p.name ? ' active' : '');
    item.innerHTML = `<span class="profile-dot">⬤</span><span class="pname">${escHtml(p.name)}</span><small style="color:var(--fg2)">${escHtml(p.username + '@' + p.host)}</small>`;
    item.addEventListener('click', () => fillProfileForm(p));
    list.appendChild(item);
  });
}

function fillProfileForm(p) {
  selectedProfile = p.name;
  document.getElementById('ssh-name').value = p.name;
  document.getElementById('ssh-host').value = p.host;
  document.getElementById('ssh-port').value = p.port || 22;
  document.getElementById('ssh-user').value = p.username;
  document.getElementById('ssh-auth').value = p.auth || 'password';
  document.getElementById('ssh-auth').dispatchEvent(new Event('change'));
  document.getElementById('ssh-key').value  = p.key_path || '';
  document.getElementById('ssh-form-title').textContent = p.name;
  loadSshProfiles();
}

document.getElementById('ssh-auth').addEventListener('change', () => {
  const v = document.getElementById('ssh-auth').value;
  document.getElementById('ssh-pass-row').classList.toggle('hidden', v !== 'password');
  document.getElementById('ssh-key-row').classList.toggle('hidden',  v !== 'key');
});

document.getElementById('btn-new-profile').addEventListener('click', () => {
  selectedProfile = null;
  ['ssh-name','ssh-host','ssh-user','ssh-pass','ssh-key'].forEach(id =>
    document.getElementById(id).value = '');
  document.getElementById('ssh-port').value = '22';
  document.getElementById('ssh-auth').value = 'password';
  document.getElementById('ssh-auth').dispatchEvent(new Event('change'));
  document.getElementById('ssh-form-title').textContent = 'New Connection';
});

document.getElementById('btn-ssh-connect').addEventListener('click', async () => {
  const body = {
    name:     document.getElementById('ssh-name').value.trim(),
    host:     document.getElementById('ssh-host').value.trim(),
    port:     document.getElementById('ssh-port').value,
    username: document.getElementById('ssh-user').value.trim(),
    auth:     document.getElementById('ssh-auth').value,
    password: document.getElementById('ssh-pass').value,
    key_path: document.getElementById('ssh-key').value.trim(),
  };
  setSshStatus('Connecting…', 'var(--yellow)');
  const r = await fetch('/api/ssh/connect', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (d.error) {
    setSshStatus('Error: ' + d.error, 'var(--red)');
    return;
  }
  sshConnected = true;
  setSshStatus(`Connected — ${body.username}@${body.host}`, 'var(--green)');
  document.getElementById('btn-ssh-connect').disabled    = true;
  document.getElementById('btn-ssh-disconnect').disabled = false;
  document.getElementById('conn-badge').textContent = `⬤ ${body.name}`;
  document.getElementById('conn-badge').className = 'badge badge-on';
  document.getElementById('ssh-info-body').textContent =
    `Host:     ${body.host}\nUser:     ${body.username}\nHome:     ${d.home || '?'}`;
  loadSshProfiles();
  // Load remote home in file browser
  if (d.home) loadDir(d.home, true);
});

document.getElementById('btn-ssh-disconnect').addEventListener('click', async () => {
  await fetch('/api/ssh/disconnect', { method: 'POST' });
  sshConnected = false;
  setSshStatus('Disconnected', 'var(--fg2)');
  document.getElementById('btn-ssh-connect').disabled    = false;
  document.getElementById('btn-ssh-disconnect').disabled = true;
  document.getElementById('conn-badge').textContent = '⬤ Local';
  document.getElementById('conn-badge').className = 'badge badge-off';
  document.getElementById('ssh-info-body').textContent = 'Connect to a server to see details.';
});

document.getElementById('btn-ssh-delete').addEventListener('click', async () => {
  const name = document.getElementById('ssh-name').value.trim();
  if (!name || !confirm(`Delete profile "${name}"?`)) return;
  await fetch('/api/ssh/delete_profile', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name }),
  });
  loadSshProfiles();
});

function setSshStatus(msg, color) {
  const el = document.getElementById('ssh-status');
  el.textContent = msg;
  el.style.color = color;
}

// ═══════════════════════════════════════════════════════════════════════════
// HPC tab
// ═══════════════════════════════════════════════════════════════════════════
function getHpcConfig() {
  const mail = [...document.querySelectorAll('.mail-chk:checked')].map(c => c.value);
  return {
    name:         document.getElementById('h-name').value,
    partition:    document.getElementById('h-part').value,
    nodes:        +document.getElementById('h-nodes').value,
    ntasks:       +document.getElementById('h-ntasks').value,
    cpus_per_task:+document.getElementById('h-cpt').value,
    mem:          document.getElementById('h-mem').value,
    walltime:     document.getElementById('h-wtime').value,
    omp_threads:  +document.getElementById('h-omp').value,
    base_dir:     document.getElementById('h-base').value,
    log_dir:      document.getElementById('h-logdir').value,
    run_dir:      document.getElementById('h-rundir').value,
    input_file:   document.getElementById('h-inp').value,
    binary:       document.getElementById('h-bin').value,
    lmp_extra:    document.getElementById('h-lmpextra').value,
    use_singularity: document.getElementById('h-use-sif').checked,
    sif:          document.getElementById('h-sif').value,
    singularity_bin: document.getElementById('h-sing').value,
    bind:         document.getElementById('h-bind').value,
    email:        document.getElementById('h-email').value,
    mail_types:   mail,
    extra_sbatch: document.getElementById('h-extra').value.split('\n').filter(Boolean),
    modules:      hpcModules,
  };
}

document.getElementById('h-use-sif').addEventListener('change', () => {
  document.getElementById('sif-fields').style.display =
    document.getElementById('h-use-sif').checked ? '' : 'none';
});

document.getElementById('btn-hpc-gen').addEventListener('click', async () => {
  const r = await fetch('/api/hpc/script', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(getHpcConfig()),
  });
  const d = await r.json();
  document.getElementById('hpc-script-pre').textContent = d.script || d.error;
});

document.getElementById('btn-hpc-submit').addEventListener('click', async () => {
  if (!sshConnected) { alert('Connect to HPC via SSH first (SSH tab).'); return; }
  if (!confirm('Submit SLURM job?')) return;
  const r = await fetch('/api/hpc/submit', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ config: getHpcConfig() }),
  });
  const d = await r.json();
  alert(d.error || `Submitted! Job ID: ${d.job_id || '?'}\n\n${d.output || ''}`);
  if (!d.error) refreshQueue();
});

document.getElementById('btn-hpc-copy').addEventListener('click', () => {
  navigator.clipboard.writeText(document.getElementById('hpc-script-pre').textContent)
    .then(() => alert('Copied to clipboard!'));
});

document.getElementById('btn-hpc-download').addEventListener('click', () => {
  const txt  = document.getElementById('hpc-script-pre').textContent;
  const name = document.getElementById('h-name').value || 'lammps_job';
  const blob = new Blob([txt], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name + '.sh';
  a.click();
});

document.getElementById('btn-hpc-refresh').addEventListener('click', refreshQueue);
async function refreshQueue() {
  if (!sshConnected) {
    document.getElementById('hpc-queue-pre').textContent = 'Connect to HPC via SSH to see queue.';
    return;
  }
  const r = await fetch('/api/hpc/queue');
  const d = await r.json();
  document.getElementById('hpc-queue-pre').textContent = d.error || d.output || '(empty queue)';
}

document.getElementById('btn-hpc-cancel').addEventListener('click', async () => {
  const jobId = document.getElementById('h-cancel-job').value.trim();
  if (!jobId) { alert('Enter a job ID'); return; }
  if (!confirm(`Cancel job ${jobId}?`)) return;
  const r = await fetch('/api/hpc/cancel', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ job_id: jobId }),
  });
  const d = await r.json();
  alert(d.error || d.output || 'Cancelled');
  refreshQueue();
});

// Modules
document.getElementById('btn-add-mod').addEventListener('click', () => {
  const v = document.getElementById('h-mod-input').value.trim();
  if (!v) return;
  hpcModules.push(v);
  document.getElementById('h-mod-input').value = '';
  renderModules();
});
document.getElementById('h-mod-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('btn-add-mod').click();
});
function renderModules() {
  const list = document.getElementById('h-modules-list');
  list.innerHTML = hpcModules.map((m, i) =>
    `<span class="tag">${escHtml(m)}<span class="tag-del" data-i="${i}">×</span></span>`
  ).join('');
  list.querySelectorAll('.tag-del').forEach(el =>
    el.addEventListener('click', () => {
      hpcModules.splice(+el.dataset.i, 1);
      renderModules();
    })
  );
}

// HPC config save/load (localStorage)
const HPC_KEY = 'lammps_hpc_config';
document.getElementById('btn-hpc-save-cfg').addEventListener('click', () => {
  localStorage.setItem(HPC_KEY, JSON.stringify(getHpcConfig()));
  alert('HPC config saved to browser storage.');
});
document.getElementById('btn-hpc-load-cfg').addEventListener('click', () => {
  const raw = localStorage.getItem(HPC_KEY);
  if (!raw) { alert('No saved config found.'); return; }
  applyHpcConfig(JSON.parse(raw));
});
function applyHpcConfig(c) {
  const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.value = v; };
  set('h-name', c.name); set('h-part', c.partition);
  set('h-nodes', c.nodes); set('h-ntasks', c.ntasks); set('h-cpt', c.cpus_per_task);
  set('h-mem', c.mem); set('h-wtime', c.walltime); set('h-omp', c.omp_threads);
  set('h-base', c.base_dir); set('h-logdir', c.log_dir); set('h-rundir', c.run_dir);
  set('h-inp', c.input_file); set('h-bin', c.binary); set('h-lmpextra', c.lmp_extra);
  set('h-sif', c.sif); set('h-sing', c.singularity_bin); set('h-bind', c.bind);
  set('h-email', c.email); set('h-extra', (c.extra_sbatch || []).join('\n'));
  if (typeof c.use_singularity !== 'undefined')
    document.getElementById('h-use-sif').checked = c.use_singularity;
  document.getElementById('h-use-sif').dispatchEvent(new Event('change'));
  document.querySelectorAll('.mail-chk').forEach(ch =>
    ch.checked = (c.mail_types || []).includes(ch.value));
  hpcModules = c.modules || [];
  renderModules();
}

// ═══════════════════════════════════════════════════════════════════════════
// AI tab
// ═══════════════════════════════════════════════════════════════════════════
async function refreshAiModels() {
  const sel = document.getElementById('ai-model-sel');
  const r = await fetch('/api/ai/models');
  const d = await r.json();
  const prev = sel.value;
  sel.innerHTML = d.models.length
    ? d.models.map(m => `<option value="${m}">${m}</option>`).join('')
    : `<option value="">(no models — click ⬇ Get Model)</option>`;
  if (d.models.includes(prev)) sel.value = prev;
  const status = document.getElementById('ai-status');
  if (d.error && !d.models.length) {
    status.textContent = '● ' + d.error;
    status.style.color = 'var(--red)';
  } else if (d.models.length) {
    status.textContent = `● ${d.models.length} model(s)`;
    status.style.color = 'var(--green)';
  } else {
    status.textContent = '● No models downloaded';
    status.style.color = 'var(--yellow)';
  }
}

document.getElementById('btn-ai-refresh').addEventListener('click', refreshAiModels);
document.getElementById('btn-ai-clear').addEventListener('click', async () => {
  await fetch('/api/ai/history', { method: 'DELETE' });
  document.getElementById('chat-view').innerHTML = '';
  aiPartial = '';
});

document.getElementById('btn-ai-send').addEventListener('click', sendAiMessage);
document.getElementById('ai-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAiMessage(); }
});

async function sendAiMessage() {
  const input = document.getElementById('ai-input');
  const text  = input.value.trim();
  if (!text || aiStreaming) return;
  const model    = document.getElementById('ai-model-sel').value;
  const cpu_mode = document.getElementById('ai-cpu-chk').checked;
  if (!model) { alert('No model selected. Download one with ⬇ Get Model.'); return; }
  input.value = '';
  appendChatBubble('user', text);
  aiPartial = '';
  aiStreaming = true;
  document.getElementById('btn-ai-send').disabled = true;
  document.getElementById('btn-ai-stop').disabled = false;
  appendAiBubble('');   // placeholder
  socket.emit('ai_send', { message: text, model, cpu_mode });
}

document.getElementById('btn-ai-stop').addEventListener('click', () => {
  socket.emit('ai_stop', {});
});

socket.on('ai_token', d => {
  aiPartial += d.token;
  if (!aiPending) {
    aiPending = true;
    setTimeout(flushAi, 80);
  }
});

socket.on('ai_done', () => {
  flushAi();
  aiStreaming = false;
  aiPending = false;
  document.getElementById('btn-ai-send').disabled = false;
  document.getElementById('btn-ai-stop').disabled = true;
});

socket.on('ai_error', d => {
  aiStreaming = false;
  document.getElementById('btn-ai-send').disabled = false;
  document.getElementById('btn-ai-stop').disabled = true;
  const chat = document.getElementById('chat-view');
  const last = chat.querySelector('.bubble-ai:last-child');
  if (last) last.remove();
  appendChatBubble('system', '⚠ Error: ' + d.message);
});

function flushAi() {
  aiPending = false;
  const chat = document.getElementById('chat-view');
  let bubble = chat.querySelector('.bubble-ai-streaming');
  if (!bubble) { appendAiBubble(''); bubble = chat.querySelector('.bubble-ai-streaming'); }
  if (!bubble) return;
  const { thinking, response } = splitThink(aiPartial);
  bubble.innerHTML = buildAiHtml(thinking, response, aiStreaming);
  chat.scrollTop = chat.scrollHeight;
}

function splitThink(text) {
  const m1 = text.match(/^<think>([\s\S]*?)<\/think>([\s\S]*)/);
  if (m1) return { thinking: m1[1].trim(), response: m1[2].trim() };
  const m2 = text.match(/^<think>([\s\S]*)/);
  if (m2) return { thinking: m2[1].trim(), response: '' };
  return { thinking: '', response: text };
}

function buildAiHtml(thinking, response, streaming) {
  let html = '';
  if (thinking) {
    html += `<details class="thinking-block" ${streaming ? '' : 'open'}><summary>💭 Thinking…</summary><div>${escHtml(thinking)}</div></details>`;
  }
  if (response) {
    html += marked.parse(response);
  } else if (streaming && !thinking) {
    html += '<span style="color:var(--fg2)">…</span>';
  }
  return html;
}

function appendChatBubble(role, text) {
  const chat = document.getElementById('chat-view');
  const div  = document.createElement('div');
  if (role === 'user') {
    div.className = 'bubble bubble-user';
    div.innerHTML = `<div class="role">You</div>${escHtml(text).replace(/\n/g,'<br>')}`;
  } else {
    div.className = 'bubble bubble-ai';
    div.innerHTML = `<div class="role">AI</div>${escHtml(text)}`;
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function appendAiBubble(html) {
  const chat = document.getElementById('chat-view');
  // Remove old streaming bubble if any
  chat.querySelectorAll('.bubble-ai-streaming').forEach(el => el.classList.remove('bubble-ai-streaming'));
  const div = document.createElement('div');
  div.className = 'bubble bubble-ai bubble-ai-streaming';
  div.innerHTML = `<div class="role">AI</div>${html}`;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

// ── Model download dialog ──────────────────────────────────────────────────
document.getElementById('btn-ai-get-model').addEventListener('click', () => {
  document.getElementById('modal-overlay').classList.remove('hidden');
  // select recommended row by default
  document.querySelectorAll('#model-table tbody tr').forEach(tr => tr.classList.remove('selected'));
  const rec = document.querySelector('#model-table tr.recommended');
  if (rec) rec.classList.add('selected');
});
document.getElementById('btn-modal-cancel').addEventListener('click', () =>
  document.getElementById('modal-overlay').classList.add('hidden'));
document.querySelectorAll('#model-table tbody tr').forEach(tr =>
  tr.addEventListener('click', () => {
    document.querySelectorAll('#model-table tbody tr').forEach(r => r.classList.remove('selected'));
    tr.classList.add('selected');
  })
);
document.getElementById('btn-modal-dl').addEventListener('click', () => {
  let model = document.getElementById('modal-custom').value.trim();
  if (!model) {
    const sel = document.querySelector('#model-table tbody tr.selected');
    if (!sel) { alert('Select a model first.'); return; }
    model = sel.dataset.model;
  }
  document.getElementById('modal-overlay').classList.add('hidden');
  startPull(model);
});

function startPull(model) {
  document.getElementById('dl-bar-row').classList.remove('hidden');
  document.getElementById('dl-label').textContent = `⬇ Pulling ${model}…`;
  document.getElementById('dl-bar').style.width = '0%';
  document.getElementById('dl-pct').textContent = '0%';
  const status = document.getElementById('ai-status');
  status.textContent = `● Downloading ${model}…`;
  status.style.color = 'var(--yellow)';
  socket.emit('ai_pull', { model });
}

document.getElementById('btn-dl-cancel').addEventListener('click', () => {
  socket.emit('pull_stop', {});
  document.getElementById('dl-bar-row').classList.add('hidden');
});

socket.on('pull_progress', d => {
  document.getElementById('dl-bar-row').classList.remove('hidden');
  const label = d.total_gb > 0
    ? `⬇ ${d.model} — ${d.done_gb.toFixed(2)} / ${d.total_gb.toFixed(1)} GB`
    : `⬇ ${d.status}…`;
  document.getElementById('dl-label').textContent = label;
  document.getElementById('dl-bar').style.width = d.pct + '%';
  document.getElementById('dl-pct').textContent  = d.pct + '%';
});

socket.on('pull_done', d => {
  document.getElementById('dl-bar-row').classList.add('hidden');
  const status = document.getElementById('ai-status');
  if (d.success) {
    status.textContent = `● ${d.model} ready`;
    status.style.color = 'var(--green)';
    refreshAiModels();
  } else {
    status.textContent = '● Download failed';
    status.style.color = 'var(--red)';
    alert('Download failed: ' + (d.error || 'unknown error'));
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════════
function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ═══════════════════════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════════════════════
(async function init() {
  initEditor();

  // Load initial file tree
  const st = await fetch('/api/status').then(r => r.json()).catch(() => ({}));
  loadDir(st.working_dir || document.location.hostname || '~');

  // SSH status on load
  const ss = await fetch('/api/ssh/status').then(r => r.json()).catch(() => ({}));
  if (ss.connected && ss.profile) {
    sshConnected = true;
    document.getElementById('conn-badge').textContent = `⬤ ${ss.profile.name || ss.profile.host}`;
    document.getElementById('conn-badge').className = 'badge badge-on';
    document.getElementById('btn-ssh-connect').disabled    = true;
    document.getElementById('btn-ssh-disconnect').disabled = false;
    setSshStatus(`Connected — ${ss.profile.username}@${ss.profile.host}`, 'var(--green)');
  }

  // AI models
  refreshAiModels();

  // Plot log path defaults
  document.getElementById('plot-log-path').value = (st.working_dir || '') + '/log.lammps';
})();
