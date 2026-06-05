'use strict';
// ═══════════════════════════════════════════════════════════════════════════
// LAMMPS Dashboard — browser client (full feature parity)
// ═══════════════════════════════════════════════════════════════════════════
const socket = io();

// ── Global state ──────────────────────────────────────────────────────────
let editor        = null;
let thermoData    = null;
let subplotCharts = [];
let sshConnected  = false;
let currentFilePath   = '';
let currentFileRemote = false;
let currentDir    = '';
let aiPartial     = '';
let aiPending     = false;
let aiStreaming    = false;
let aiAttachText  = '';
let selectedProfile   = null;
let hpcModules    = [];
let hpcSelectedRow    = null;   // {id, name, workdir}
let logLineCount  = 0;

const CHART_COLORS = [
  '#4fc3f7','#81c784','#ffd54f','#ef5350',
  '#ce93d8','#80cbc4','#ffb74d','#e57373',
];

// ═══════════════════════════════════════════════════════════════════════════
// Tab switching
// ═══════════════════════════════════════════════════════════════════════════
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.remove('hidden');
    if (btn.dataset.tab === 'ai')    refreshAiModels();
    if (btn.dataset.tab === 'ssh')   loadSshProfiles();
    if (btn.dataset.tab === 'plots' && thermoData) buildColCheckboxes(thermoData.headers);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// CodeMirror + LAMMPS mode
// ═══════════════════════════════════════════════════════════════════════════
CodeMirror.defineSimpleMode('lammps', {
  start: [
    { regex: /#.*/, token: 'comment' },
    { regex: /\$\{[^}]+\}|v_\w+|c_\w+|f_\w+/, token: 'variable-2' },
    { regex: /(?:units|atom_style|boundary|dimension|pair_style|pair_coeff|bond_style|bond_coeff|angle_style|angle_coeff|dihedral_style|dihedral_coeff|improper_style|improper_coeff|kspace_style|kspace_modify|neighbor|neigh_modify|atom_modify|comm_modify|fix|unfix|compute|uncompute|dump|undump|group|region|create_box|create_atoms|read_data|read_restart|write_data|write_restart|minimize|run|timestep|thermo|thermo_style|thermo_modify|velocity|reset_timestep|log|echo|print|variable|label|jump|if|then|else|include|shell|package|suffix|newton|processors|clear|lattice|mass|replicate|change_box)\b/, token: 'keyword' },
    { regex: /(?:lj\/cut|lj\/long|coul\/long|coul\/cut|reax\/c|tersoff|eam|eam\/alloy|sw|meam|airebo|table|morse|buck|born|yukawa|dpd|hybrid|overlay)\b/, token: 'atom' },
    { regex: /(?:nve|nvt|npt|langevin|berendsen|rescale|minimize|rigid|shake|spring|indent|wall|deform|ave\/time|ave\/atom|ave\/chunk|rerun|temp|press|pe|ke|etotal|lx|ly|lz|vol|density|pxx|pyy|pzz|pxy|pxz|pyz|enthalpy|step|cpu|elapsed|elaplong|dt|time|atoms|bonds|angles)\b/, token: 'string' },
    { regex: /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/, token: 'number' },
    { regex: /[=<>!]+/, token: 'operator' },
  ],
  meta: { lineComment: '#' }
});

function initEditor() {
  editor = CodeMirror(document.getElementById('editor-wrap'), {
    mode: 'lammps', theme: 'dracula', lineNumbers: true, matchBrackets: true,
    indentWithTabs: false, tabSize: 4, lineWrapping: false,
    value: '# Open a file from the tree to start editing\n',
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// File browser
// ═══════════════════════════════════════════════════════════════════════════
async function loadDir(path, remote = false) {
  currentDir = path;
  document.getElementById('path-bar').value = remote ? `[SSH] ${path}` : path;
  const url = remote ? `/api/ssh/files?path=${enc(path)}` : `/api/files?dir=${enc(path)}`;
  try {
    const d = await GET(url);
    if (d.error) { alert(d.error); return; }
    renderTree(d.entries, d.parent, remote);
  } catch (e) { alert('Error: ' + e); }
}

function renderTree(entries, parent, remote) {
  const tree = document.getElementById('file-tree');
  tree.innerHTML = '';
  if (parent !== null) {
    tree.appendChild(makeTreeItem('..', '↑', 'tree-dir', () => loadDir(parent, remote)));
  }
  entries.forEach(e => {
    const icon = e.type === 'dir' ? '📂' : fileIcon(e.name);
    const item = makeTreeItem(e.name, icon, e.type === 'dir' ? 'tree-dir' : 'tree-file', () => {
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
  const div = document.createElement('div');
  div.className = `tree-item ${cls}`;
  div.innerHTML = `<span class="icon">${icon}</span><span class="name">${esc(name)}</span>`;
  div.addEventListener('click', onClick);
  return div;
}

function fileIcon(n) {
  if (/\.py$/i.test(n)) return '🐍';
  if (/\.(sh|bash)$/i.test(n)) return '⚙';
  if (/log/i.test(n)) return '📋';
  if (/\.(png|jpg|gif|svg)$/i.test(n)) return '🖼';
  if (/\.(in|lammps|lmp)$/i.test(n)) return '⚛';
  return '📄';
}

async function openFile(path, remote = false) {
  const url = remote ? `/api/ssh/file?path=${enc(path)}` : `/api/file?path=${enc(path)}`;
  try {
    const d = await GET(url);
    if (d.error) { alert(d.error); return; }
    editor.setValue(d.content);
    currentFilePath   = path;
    currentFileRemote = remote;
    document.getElementById('editor-filename').textContent = (remote ? '[SSH] ' : '') + path;
    // Auto-populate run fields
    const dir  = path.substring(0, path.lastIndexOf('/')) || '/';
    const base = path.substring(path.lastIndexOf('/') + 1);
    document.getElementById('run-dir').value   = dir;
    document.getElementById('run-input').value = base;
    document.getElementById('plot-log-path').value = dir + '/log.lammps';
    // Show SSH-only buttons if remote
    document.querySelectorAll('.btn-ssh-only').forEach(b =>
      b.classList.toggle('hidden', !remote));
  } catch (e) { alert('Error: ' + e); }
}

async function saveFile() {
  if (!currentFilePath) { alert('No file open'); return; }
  const url = currentFileRemote ? '/api/ssh/file' : '/api/file';
  const d = await POST(url, { path: currentFilePath, content: editor.getValue() });
  if (d.error) alert('Save failed: ' + d.error);
  else toast('Saved: ' + currentFilePath);
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
  const remote = document.getElementById('path-bar').value.startsWith('[SSH]');
  const parent = currentDir === '/' ? '/' : currentDir.substring(0, currentDir.lastIndexOf('/')) || '/';
  loadDir(parent, remote);
});
document.getElementById('btn-save').addEventListener('click', saveFile);

// ── Save As — file picker ─────────────────────────────────────────────────
let _saveAsDir    = '';
let _saveAsRemote = false;

function openSaveAs() {
  _saveAsRemote = currentFileRemote;
  _saveAsDir = currentFilePath
    ? (currentFilePath.lastIndexOf('/') > 0
        ? currentFilePath.substring(0, currentFilePath.lastIndexOf('/'))
        : '/')
    : (currentDir || '/home');
  const basename = currentFilePath
    ? currentFilePath.substring(currentFilePath.lastIndexOf('/') + 1)
    : '';
  document.getElementById('saveas-filename').value = basename;
  document.getElementById('saveas-overlay').classList.remove('hidden');
  loadSaveAsTree(_saveAsDir);
}

async function loadSaveAsTree(path) {
  _saveAsDir = path;
  document.getElementById('saveas-dir-input').value =
    _saveAsRemote ? `[SSH] ${path}` : path;
  const url = _saveAsRemote
    ? `/api/ssh/files?path=${enc(path)}`
    : `/api/files?dir=${enc(path)}`;
  let d;
  try { d = await GET(url); } catch(e) { alert('Error: ' + e); return; }
  if (d.error) { alert(d.error); return; }
  const tree = document.getElementById('saveas-tree');
  tree.innerHTML = '';
  if (d.parent !== null) {
    tree.appendChild(makeTreeItem('..', '↑', 'tree-dir', () => loadSaveAsTree(d.parent)));
  }
  d.entries.forEach(e => {
    const item = makeTreeItem(
      e.name,
      e.type === 'dir' ? '📂' : fileIcon(e.name),
      e.type === 'dir' ? 'tree-dir' : 'tree-file',
      () => {
        if (e.type === 'dir') {
          loadSaveAsTree(e.path);
        } else {
          document.getElementById('saveas-filename').value = e.name;
        }
      }
    );
    tree.appendChild(item);
  });
}

document.getElementById('btn-save-as').addEventListener('click', openSaveAs);

document.getElementById('saveas-go-btn').addEventListener('click', () => {
  let p = document.getElementById('saveas-dir-input').value.trim();
  const remote = p.startsWith('[SSH]');
  if (remote) p = p.replace(/^\[SSH\]\s*/, '');
  _saveAsRemote = remote;
  loadSaveAsTree(p || '/');
});
document.getElementById('saveas-dir-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('saveas-go-btn').click();
});
document.getElementById('saveas-up-btn').addEventListener('click', () => {
  const parent = (_saveAsDir === '/' || !_saveAsDir)
    ? '/'
    : _saveAsDir.substring(0, _saveAsDir.lastIndexOf('/')) || '/';
  loadSaveAsTree(parent);
});
document.getElementById('btn-saveas-cancel').addEventListener('click', () => {
  document.getElementById('saveas-overlay').classList.add('hidden');
});
document.getElementById('btn-saveas-save').addEventListener('click', async () => {
  const name = document.getElementById('saveas-filename').value.trim();
  if (!name) { alert('Enter a filename'); return; }
  const newPath = (_saveAsDir.replace(/\/$/, '') || '') + '/' + name;
  currentFilePath   = newPath;
  currentFileRemote = _saveAsRemote;
  document.getElementById('editor-filename').textContent =
    (_saveAsRemote ? '[SSH] ' : '') + newPath;
  document.getElementById('saveas-overlay').classList.add('hidden');
  await saveFile();
});
document.getElementById('btn-new-file').addEventListener('click', async () => {
  const name = prompt('New file name:'); if (!name) return;
  const path = currentDir.replace(/\/$/, '') + '/' + name;
  const url = sshConnected ? '/api/ssh/file' : '/api/file';
  await POST(url, { path, content: '' });
  await loadDir(currentDir, sshConnected);
});
document.getElementById('btn-new-dir').addEventListener('click', async () => {
  const name = prompt('New folder name:'); if (!name) return;
  await POST('/api/mkdir', { path: currentDir.replace(/\/$/, '') + '/' + name });
  await loadDir(currentDir, sshConnected);
});
document.getElementById('btn-use-as-input').addEventListener('click', () => {
  if (!currentFilePath) { alert('No file open'); return; }
  const dir  = currentFilePath.substring(0, currentFilePath.lastIndexOf('/')) || '/';
  const base = currentFilePath.substring(currentFilePath.lastIndexOf('/') + 1);
  document.getElementById('run-input').value = base;
  document.getElementById('run-dir').value   = dir;
  if (currentFileRemote) document.getElementById('run-remote').checked = true;
  document.querySelector('[data-tab=run]').click();
  toast('Input set: ' + base);
});

// SSH upload/download from editor toolbar
document.getElementById('btn-ssh-upload-file').addEventListener('click', () => {
  document.getElementById('file-upload-input').click();
});
document.getElementById('file-upload-input').addEventListener('change', async e => {
  const file = e.target.files[0]; if (!file) return;
  const remotePath = currentDir.replace(/\/$/, '') + '/' + file.name;
  await uploadFileToRemote(file, remotePath);
  await loadDir(currentDir, true);
  e.target.value = '';
});
document.getElementById('btn-ssh-download-file').addEventListener('click', () => {
  if (!currentFilePath) return;
  window.location = `/api/ssh/download_file?path=${enc(currentFilePath)}`;
});

// Pane resize
(function() {
  const handle = document.getElementById('pane-resize');
  const panel  = document.getElementById('tree-panel');
  let drag = false, sx = 0, sw = 0;
  handle.addEventListener('mousedown', e => { drag=true; sx=e.clientX; sw=panel.offsetWidth; document.body.style.cursor='col-resize'; e.preventDefault(); });
  document.addEventListener('mousemove', e => { if (!drag) return; panel.style.width = Math.max(150,Math.min(600,sw+e.clientX-sx))+'px'; });
  document.addEventListener('mouseup', () => { drag=false; document.body.style.cursor=''; });
})();

// ═══════════════════════════════════════════════════════════════════════════
// Run tab
// ═══════════════════════════════════════════════════════════════════════════
const logView = document.getElementById('log-view');

function appendLog(text, cls = '') {
  logLineCount++;
  const div = document.createElement('div');
  div.className = 'log-line' + (cls ? ' ' + cls : '');
  div.textContent = text;
  logView.appendChild(div);
  document.getElementById('log-count').textContent = logLineCount + ' lines';
  if (document.getElementById('log-autoscroll').checked)
    logView.scrollTop = logView.scrollHeight;
}

document.getElementById('btn-run').addEventListener('click', async () => {
  const inp    = document.getElementById('run-input').value.trim();
  const dir    = document.getElementById('run-dir').value.trim();
  const np     = document.getElementById('run-np').value;
  const bin    = document.getElementById('run-bin').value.trim();
  const extra  = document.getElementById('run-extra').value.trim();
  const remote = document.getElementById('run-remote').checked;
  if (!inp) { alert('Enter an input file name'); return; }
  const d = await POST('/api/run', { input_file:inp, working_dir:dir, np, lmp_bin:bin, extra_args:extra, remote });
  if (d.error) { alert(d.error); return; }
  setRunning(true);
  if (d.working_dir) {
    _state_wd = d.working_dir;
    document.getElementById('plot-log-path').value = d.working_dir.replace(/\/$/, '') + '/log.lammps';
  }
});

document.getElementById('btn-stop').addEventListener('click', () => {
  fetch('/api/stop', { method:'POST' });
});

document.getElementById('btn-parse-log').addEventListener('click', async () => {
  const path   = document.getElementById('plot-log-path').value.trim() || 'log.lammps';
  const remote = sshConnected && document.getElementById('run-remote').checked;
  const d = await GET(`/api/parse_log?path=${enc(path)}&remote=${remote}`);
  if (d.error) { alert(d.error); return; }
  if (!d.headers || !d.headers.length) { alert('No thermo data found.'); return; }
  thermoData = d;
  buildColCheckboxes(d.headers);
  document.querySelector('[data-tab=plots]').click();
});

document.getElementById('btn-clear-log').addEventListener('click', () => {
  logView.innerHTML = ''; logLineCount = 0;
  document.getElementById('log-count').textContent = '0 lines';
});

document.getElementById('btn-browse-input').addEventListener('click', () => {
  document.querySelector('[data-tab=files]').click();
});
document.getElementById('btn-browse-dir').addEventListener('click', () => {
  document.querySelector('[data-tab=files]').click();
});

document.getElementById('btn-detect-bin').addEventListener('click', async () => {
  toast('Detecting LAMMPS binary…');
  const d = await GET('/api/run/detect_binary');
  if (d.binary) {
    document.getElementById('run-bin').value = d.binary;
    toast('Found: ' + d.binary);
  } else {
    alert('LAMMPS binary not found — set manually.');
  }
});

function setRunning(on) {
  document.getElementById('btn-run').disabled  = on;
  document.getElementById('btn-stop').disabled = !on;
  const bar = document.getElementById('run-status');
  bar.textContent = on ? '● Running…' : 'Idle';
  bar.style.color = on ? 'var(--green)' : 'var(--fg2)';
}

function updateRunTargetBar() {
  const bar = document.getElementById('run-target-bar');
  const hpcMode = document.getElementById('h-hpc-mode')?.checked;
  if (sshConnected && hpcMode) {
    bar.textContent = '⚡ Run target: HPC — jobs routed via sbatch';
    bar.style.borderColor = 'var(--yellow)';
    bar.style.color = 'var(--yellow)';
    bar.style.background = '#1a1a0a';
  } else if (sshConnected) {
    const host = document.getElementById('ssh-host').value || 'remote';
    bar.textContent = `🔗 Run target: SSH — ${host}`;
    bar.style.borderColor = 'var(--accent)';
    bar.style.color = 'var(--accent)';
    bar.style.background = '#0a1a2a';
  } else {
    bar.textContent = '▶ Run target: 💻 Local machine';
    bar.style.borderColor = 'var(--green)';
    bar.style.color = 'var(--green)';
    bar.style.background = '#1a2a1a';
  }
}

// Socket.IO
socket.on('log_line', d => appendLog(d.line,
  /ERROR|FATAL/i.test(d.line)   ? 'log-err'  :
  /WARNING/i.test(d.line)       ? 'log-warn' :
  /^\s*\d+\s+[\d.\-e]+/.test(d.line) ? 'log-ok'   : ''));

socket.on('status', d => {
  setRunning(d.running);
  if (d.running && d.cmd) {
    appendLog('▶ ' + d.cmd, 'log-ok');
  }
  if (!d.running) {
    const ok = d.returncode === 0;
    appendLog(`⬛ Finished — exit code: ${d.returncode}`, ok ? 'log-ok' : 'log-err');
  }
});

socket.on('thermo_ready', d => {
  thermoData = d;
  buildColCheckboxes(d.headers);
  appendLog('📊 Thermo data ready — switching to Plots tab…', 'log-ok');
  setTimeout(() => document.querySelector('[data-tab=plots]').click(), 800);
});

// ═══════════════════════════════════════════════════════════════════════════
// Plots tab
// ═══════════════════════════════════════════════════════════════════════════
function buildColCheckboxes(headers) {
  const selX  = document.getElementById('plot-x');
  const cont  = document.getElementById('plot-col-checks');
  selX.innerHTML = headers.map(h => `<option value="${h}">${h}</option>`).join('');
  cont.innerHTML = '';
  const skip = new Set(['Step']);
  const defaults = new Set(['Temp','PotEng','TotEng','Press','KinEng','E_pair','E_bond']);
  headers.filter(h => !skip.has(h)).forEach((h, i) => {
    const color = CHART_COLORS[i % CHART_COLORS.length];
    const label = document.createElement('label');
    label.className = 'col-check-item';
    label.innerHTML =
      `<input type="checkbox" ${defaults.has(h) ? 'checked' : ''}/>`+
      `<span class="col-check-swatch" style="background:${color}"></span>`+
      `<span>${h}</span>`;
    cont.appendChild(label);
  });
}

document.getElementById('btn-all-cols').addEventListener('click', () =>
  document.querySelectorAll('#plot-col-checks input').forEach(c => c.checked = true));
document.getElementById('btn-no-cols').addEventListener('click', () =>
  document.querySelectorAll('#plot-col-checks input').forEach(c => c.checked = false));

document.getElementById('btn-plot').addEventListener('click', () => {
  if (!thermoData) { alert('No data. Run a simulation or load a log file.'); return; }
  const xKey = document.getElementById('plot-x').value;
  const yKeys = [];
  document.querySelectorAll('#plot-col-checks .col-check-item').forEach((label, i) => {
    if (label.querySelector('input').checked) {
      const name = label.querySelector('span:last-child').textContent;
      yKeys.push({ key: name, color: CHART_COLORS[i % CHART_COLORS.length] });
    }
  });
  if (!yKeys.length) { alert('Select at least one column.'); return; }
  const layout = document.getElementById('plot-layout').value;
  renderPlots(thermoData, xKey, yKeys, layout);
});

document.getElementById('btn-load-log').addEventListener('click', async () => {
  const path   = document.getElementById('plot-log-path').value.trim() || 'log.lammps';
  const remote = sshConnected && document.getElementById('run-remote').checked;
  const d = await GET(`/api/parse_log?path=${enc(path)}&remote=${remote}`);
  if (d.error) { alert(d.error); return; }
  if (!d.headers || !d.headers.length) { alert('No thermo data found.'); return; }
  thermoData = d;
  buildColCheckboxes(d.headers);
  document.getElementById('no-plot-msg').style.display = 'none';
  toast('Log loaded — ' + d.headers.length + ' columns');
});

document.getElementById('btn-save-plot').addEventListener('click', () => {
  const canvases = document.querySelectorAll('#subplot-grid canvas');
  if (!canvases.length) { alert('No plot to save'); return; }
  canvases.forEach((c, i) => {
    const a = document.createElement('a');
    a.download = `thermo_plot_${i + 1}.png`;
    a.href = c.toDataURL('image/png');
    a.click();
  });
});

function renderPlots(data, xKey, yKeys, layout) {
  const grid = document.getElementById('subplot-grid');
  // Destroy old charts
  subplotCharts.forEach(ch => ch.destroy());
  subplotCharts = [];
  grid.innerHTML = '';
  document.getElementById('no-plot-msg').style.display = 'none';
  const xVals = data.data[xKey] || [];

  if (layout === 'overlay') {
    grid.style.gridTemplateColumns = '1fr';
    const cell = document.createElement('div');
    cell.className = 'subplot-cell';
    const canvas = document.createElement('canvas');
    cell.appendChild(canvas); grid.appendChild(cell);
    const datasets = yKeys.map(({ key, color }) => ({
      label: key,
      data: (data.data[key] || []).map((v, i) => ({ x: xVals[i], y: v })),
      borderColor: color, backgroundColor: color + '22',
      borderWidth: 1.5, pointRadius: xVals.length > 500 ? 0 : 2, tension: 0.1,
    }));
    subplotCharts.push(new Chart(canvas, {
      type: 'line', data: { datasets },
      options: chartOptions(xKey, yKeys.map(y => y.key).join(', ')),
    }));
  } else {
    // Grid of separate subplots
    const n     = yKeys.length;
    const ncols = n <= 1 ? 1 : n <= 4 ? 2 : 3;
    grid.style.gridTemplateColumns = `repeat(${ncols}, 1fr)`;
    yKeys.forEach(({ key, color }) => {
      const cell   = document.createElement('div');
      cell.className = 'subplot-cell';
      const canvas = document.createElement('canvas');
      cell.appendChild(canvas); grid.appendChild(cell);
      const ys = data.data[key] || [];
      subplotCharts.push(new Chart(canvas, {
        type: 'line',
        data: { datasets: [{
          label: key,
          data: ys.map((v, i) => ({ x: xVals[i], y: v })),
          borderColor: color, backgroundColor: color + '22',
          borderWidth: 1.5, pointRadius: xVals.length > 500 ? 0 : 2, tension: 0.1,
        }] },
        options: chartOptions(xKey, key),
      }));
    });
  }
}

function chartOptions(xLabel, yLabel) {
  return {
    animation: false, responsive: true, maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#d4d4d4', font: { size: 10 } } } },
    scales: {
      x: { type:'linear', title:{ display:true, text:xLabel, color:'#8a9ab0' },
           ticks:{ color:'#8a9ab0', maxTicksLimit:8 }, grid:{ color:'#2d3139' } },
      y: { title:{ display:true, text:yLabel, color:'#8a9ab0' },
           ticks:{ color:'#8a9ab0' }, grid:{ color:'#2d3139' } },
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// SSH tab
// ═══════════════════════════════════════════════════════════════════════════
async function loadSshProfiles() {
  const d = await GET('/api/ssh/profiles');
  const list = document.getElementById('profile-list');
  list.innerHTML = '';
  (d.profiles || []).forEach(p => {
    const item = document.createElement('div');
    item.className = 'profile-item' + (selectedProfile === p.name ? ' active' : '');
    item.innerHTML = `<span class="profile-dot">⬤</span><span class="pname">${esc(p.name)}</span><small style="color:var(--fg2)">${esc(p.username+'@'+p.host)}</small>`;
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
  document.getElementById('ssh-key-row').classList.toggle('hidden', v !== 'key');
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
  const d = await POST('/api/ssh/connect', body);
  if (d.error) { setSshStatus('Error: ' + d.error, 'var(--red)'); return; }
  sshConnected = true;
  setSshStatus(`Connected — ${body.username}@${body.host}`, 'var(--green)');
  document.getElementById('btn-ssh-connect').disabled    = true;
  document.getElementById('btn-ssh-disconnect').disabled = false;
  document.getElementById('btn-ssh-upload').disabled    = false;
  document.getElementById('btn-ssh-download').disabled  = false;
  document.getElementById('conn-badge').textContent = `⬤ ${body.name || body.host}`;
  document.getElementById('conn-badge').className = 'badge badge-on';
  document.getElementById('ssh-info-body').textContent =
    `Host:    ${body.host}\nUser:    ${body.username}\nHome:    ${d.home || '?'}`;
  loadSshProfiles(); updateRunTargetBar();
  if (d.home) loadDir(d.home, true);
  document.getElementById('term-remote-chk').checked = true;
  // Auto-detect HPC features
  autoDetectHpc(body.host);
});

document.getElementById('btn-ssh-disconnect').addEventListener('click', async () => {
  await POST('/api/ssh/disconnect', {});
  sshConnected = false;
  setSshStatus('Disconnected', 'var(--fg2)');
  document.getElementById('btn-ssh-connect').disabled    = false;
  document.getElementById('btn-ssh-disconnect').disabled = true;
  document.getElementById('btn-ssh-upload').disabled    = true;
  document.getElementById('btn-ssh-download').disabled  = true;
  document.getElementById('conn-badge').textContent = '⬤ Local';
  document.getElementById('conn-badge').className = 'badge badge-off';
  document.getElementById('ssh-info-body').textContent = 'Connect to a server to see details.';
  document.getElementById('term-remote-chk').checked = false;
  updateRunTargetBar();
});

document.getElementById('btn-ssh-delete').addEventListener('click', async () => {
  const name = document.getElementById('ssh-name').value.trim();
  if (!name || !confirm(`Delete profile "${name}"?`)) return;
  await POST('/api/ssh/delete_profile', { name });
  loadSshProfiles();
});

// SSH upload (from info panel)
document.getElementById('btn-ssh-upload').addEventListener('click', () => {
  document.getElementById('ssh-upload-input').click();
});
document.getElementById('ssh-upload-input').addEventListener('change', async e => {
  const file = e.target.files[0]; if (!file) return;
  const remote = document.getElementById('ssh-remote-path').value.trim() ||
    (currentDir || '/').replace(/\/$/, '') + '/' + file.name;
  await uploadFileToRemote(file, remote);
  e.target.value = '';
});
document.getElementById('btn-ssh-download').addEventListener('click', () => {
  document.getElementById('ssh-remote-path-label').classList.toggle('hidden');
});

async function uploadFileToRemote(file, remotePath) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async e => {
      const bytes = new Uint8Array(e.target.result);
      let binary = '';
      const CHUNK = 0x8000;
      for (let i = 0; i < bytes.length; i += CHUNK)
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
      const b64 = btoa(binary);
      const d = await POST('/api/ssh/upload', { remote_path: remotePath, content: b64 });
      if (d.error) { alert('Upload failed: ' + d.error); reject(d.error); }
      else { toast('Uploaded: ' + remotePath); resolve(); }
    };
    reader.readAsArrayBuffer(file);
  });
}

function setSshStatus(msg, color) {
  const el = document.getElementById('ssh-status');
  el.textContent = msg; el.style.color = color;
}

// ═══════════════════════════════════════════════════════════════════════════
// HPC tab
// ═══════════════════════════════════════════════════════════════════════════
function getHpcConfig() {
  const mail = [...document.querySelectorAll('.mail-chk:checked')].map(c => c.value);
  return {
    name:           document.getElementById('h-name').value,
    partition:      document.getElementById('h-part').value,
    nodes:         +document.getElementById('h-nodes').value,
    ntasks:        +document.getElementById('h-ntasks').value,
    cpus_per_task: +document.getElementById('h-cpt').value,
    mem:            document.getElementById('h-mem').value,
    walltime:       document.getElementById('h-wtime').value,
    omp_threads:   +document.getElementById('h-omp').value,
    base_dir:       document.getElementById('h-base').value,
    log_dir:        document.getElementById('h-logdir').value,
    run_dir:        document.getElementById('h-rundir').value,
    input_file:     document.getElementById('h-inp').value,
    binary:         document.getElementById('h-bin').value,
    lmp_extra:      document.getElementById('h-lmpextra').value,
    use_singularity:document.getElementById('h-use-sif').checked,
    sif:            document.getElementById('h-sif').value,
    singularity_bin:document.getElementById('h-sing').value,
    bind:           document.getElementById('h-bind').value,
    email:          document.getElementById('h-email').value,
    mail_types:     mail,
    extra_sbatch:   document.getElementById('h-extra').value.split('\n').filter(Boolean),
    modules:        hpcModules,
  };
}

document.getElementById('h-use-sif').addEventListener('change', () => {
  document.getElementById('sif-fields').style.display =
    document.getElementById('h-use-sif').checked ? '' : 'none';
});

document.getElementById('h-hpc-mode').addEventListener('change', updateRunTargetBar);

document.getElementById('btn-hpc-gen').addEventListener('click', async () => {
  const d = await POST('/api/hpc/script', getHpcConfig());
  document.getElementById('hpc-script-pre').textContent = d.script || d.error;
});

document.getElementById('btn-hpc-submit').addEventListener('click', async () => {
  if (!sshConnected) { alert('Connect to HPC via SSH first (SSH tab).'); return; }
  if (!confirm('Submit SLURM job to HPC?')) return;
  const d = await POST('/api/hpc/submit', { config: getHpcConfig() });
  if (d.error) { alert('Submit failed: ' + d.error); return; }
  alert(`✔ Job submitted!\nJob ID: ${d.job_id || '?'}\n\n${d.output || ''}`);
  refreshQueue();
});

document.getElementById('btn-hpc-copy').addEventListener('click', () =>
  navigator.clipboard.writeText(document.getElementById('hpc-script-pre').textContent)
    .then(() => toast('Copied!')));

document.getElementById('btn-hpc-download-sh').addEventListener('click', () => {
  const txt  = document.getElementById('hpc-script-pre').textContent;
  const name = document.getElementById('h-name').value || 'lammps_job';
  const blob = new Blob([txt], { type: 'text/plain' });
  const a = Object.assign(document.createElement('a'),
    { href: URL.createObjectURL(blob), download: name + '.sh' });
  a.click();
});

document.getElementById('btn-hpc-sinfo').addEventListener('click', async () => {
  if (!sshConnected) { alert('Not connected'); return; }
  const d = await GET('/api/hpc/sinfo');
  alert(d.error || d.output);
});

document.getElementById('btn-hpc-qpart').addEventListener('click', async () => {
  if (!sshConnected) { alert('Not connected'); return; }
  const d = await GET('/api/hpc/partitions');
  if (d.error) { alert(d.error); return; }
  const dl = document.getElementById('partition-list');
  dl.innerHTML = (d.partitions || []).map(p => `<option value="${esc(p)}">`).join('');
  const lbl = document.getElementById('hpc-status-lbl');
  lbl.textContent = `⚡ ${d.partitions.length} partition(s): ${d.partitions.slice(0,5).join(', ')}`;
  lbl.style.color = 'var(--green)';
  toast('Partitions loaded: ' + (d.partitions || []).join(', '));
});

document.getElementById('btn-hpc-detect-sing').addEventListener('click', async () => {
  if (!sshConnected) { alert('Not connected'); return; }
  const d = await GET('/api/hpc/detect_singularity');
  if (d.binary) {
    document.getElementById('h-sing').value = d.binary;
    toast('Found: ' + d.binary);
  } else {
    alert('singularity / apptainer not found on remote.');
  }
});

document.getElementById('btn-hpc-refresh').addEventListener('click', refreshQueue);
document.getElementById('btn-hpc-queue-refresh').addEventListener('click', refreshQueue);

async function refreshQueue() {
  if (!sshConnected) {
    document.getElementById('hpc-queue-empty').textContent = 'Connect to HPC via SSH to see queue.';
    return;
  }
  const d = await GET('/api/hpc/queue');
  const tbody = document.getElementById('hpc-queue-body');
  const empty = document.getElementById('hpc-queue-empty');
  tbody.innerHTML = '';
  hpcSelectedRow = null;
  if (d.error || !d.jobs || !d.jobs.length) {
    empty.textContent = d.error || 'No active jobs.';
    empty.style.display = '';
    document.getElementById('hpc-queue-info').textContent = d.error || 'Queue is empty.';
    return;
  }
  empty.style.display = 'none';
  d.jobs.forEach(job => {
    const tr = document.createElement('tr');
    const statusCls = `status-${job.status.replace(/\s/g, '')}`;
    tr.innerHTML = [job.id, job.name, `<span class="${statusCls}">${job.status}</span>`,
      job.reason, job.time, job.partition, job.cpus, job.mem]
      .map((v, i) => i !== 2 ? `<td>${esc(String(v))}</td>` : `<td>${v}</td>`)
      .join('');
    tr.addEventListener('click', () => {
      tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
      tr.classList.add('selected');
      hpcSelectedRow = job;
    });
    tbody.appendChild(tr);
  });
  document.getElementById('hpc-queue-info').textContent =
    `${d.jobs.length} job(s) in queue — refreshed just now`;
}

document.getElementById('btn-hpc-cancel').addEventListener('click', async () => {
  if (!hpcSelectedRow) { alert('Click a job row first.'); return; }
  if (!confirm(`Cancel job ${hpcSelectedRow.id}?`)) return;
  const d = await POST('/api/hpc/cancel', { job_id: hpcSelectedRow.id });
  alert(d.error || `scancel ${hpcSelectedRow.id} sent.`);
  setTimeout(refreshQueue, 1500);
});

document.getElementById('btn-hpc-view-out').addEventListener('click', async () => {
  if (!hpcSelectedRow) { alert('Click a job row first.'); return; }
  const logDir = document.getElementById('h-logdir').value ||
    (document.getElementById('h-base').value + '/slurm_logs');
  const candidates = [
    `${logDir}/${hpcSelectedRow.name}_${hpcSelectedRow.id}.out`,
    `${logDir}/${hpcSelectedRow.id}.out`,
  ];
  for (const path of candidates) {
    const d = await GET(`/api/hpc/output?path=${enc(path)}`);
    if (!d.error) {
      editor.setValue(d.content);
      currentFilePath = path; currentFileRemote = true;
      document.getElementById('editor-filename').textContent = '[SSH] ' + path;
      document.querySelector('[data-tab=files]').click();
      toast('Opened: ' + path);
      return;
    }
  }
  alert('Output file not found. Check log directory: ' + logDir);
});

// Modules
document.getElementById('btn-add-mod').addEventListener('click', () => {
  const v = document.getElementById('h-mod-input').value.trim(); if (!v) return;
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
    `<span class="tag">${esc(m)}<span class="tag-del" data-i="${i}">×</span></span>`).join('');
  list.querySelectorAll('.tag-del').forEach(el =>
    el.addEventListener('click', () => { hpcModules.splice(+el.dataset.i, 1); renderModules(); }));
}

// HPC config: localStorage
const HPC_KEY = 'lammps_hpc_config';
document.getElementById('btn-hpc-save-cfg').addEventListener('click', () => {
  localStorage.setItem(HPC_KEY, JSON.stringify(getHpcConfig()));
  toast('HPC config saved.');
});
document.getElementById('btn-hpc-load-cfg').addEventListener('click', () => {
  const raw = localStorage.getItem(HPC_KEY);
  if (!raw) { alert('No saved config.'); return; }
  applyHpcConfig(JSON.parse(raw));
  toast('HPC config loaded.');
});
function applyHpcConfig(c) {
  const set = (id, v) => { const el=document.getElementById(id); if (el&&v!=null) el.value=v; };
  set('h-name',c.name); set('h-part',c.partition);
  set('h-nodes',c.nodes); set('h-ntasks',c.ntasks); set('h-cpt',c.cpus_per_task);
  set('h-mem',c.mem); set('h-wtime',c.walltime); set('h-omp',c.omp_threads);
  set('h-base',c.base_dir); set('h-logdir',c.log_dir); set('h-rundir',c.run_dir);
  set('h-inp',c.input_file); set('h-bin',c.binary); set('h-lmpextra',c.lmp_extra);
  set('h-sif',c.sif); set('h-sing',c.singularity_bin); set('h-bind',c.bind);
  set('h-email',c.email); set('h-extra',(c.extra_sbatch||[]).join('\n'));
  if (c.use_singularity != null) document.getElementById('h-use-sif').checked = c.use_singularity;
  document.getElementById('h-use-sif').dispatchEvent(new Event('change'));
  document.querySelectorAll('.mail-chk').forEach(ch => ch.checked=(c.mail_types||[]).includes(ch.value));
  hpcModules = c.modules || []; renderModules();
}

// Auto-detect HPC when SSH connects
const HPC_KEYWORDS = ['hpc','cluster','slurm','login','hpclogin','iitj','iiser','iisc','supercomp'];
function autoDetectHpc(host) {
  const isHpc = HPC_KEYWORDS.some(kw => host.toLowerCase().includes(kw));
  if (isHpc) {
    document.getElementById('h-hpc-mode').checked = true;
    const lbl = document.getElementById('hpc-status-lbl');
    lbl.textContent = `⚡ HPC detected — ${host} (jobs go via sbatch)`;
    lbl.style.color = 'var(--yellow)';
    updateRunTargetBar();
    // Load saved config, query partitions, detect singularity
    const saved = localStorage.getItem(HPC_KEY);
    if (saved) applyHpcConfig(JSON.parse(saved));
    setTimeout(async () => {
      const d = await GET('/api/hpc/partitions');
      if (d.partitions) {
        const dl = document.getElementById('partition-list');
        dl.innerHTML = d.partitions.map(p => `<option value="${esc(p)}">`).join('');
      }
    }, 500);
    setTimeout(async () => {
      const d = await GET('/api/hpc/detect_singularity');
      if (d.binary) document.getElementById('h-sing').value = d.binary;
    }, 1000);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// AI tab
// ═══════════════════════════════════════════════════════════════════════════
async function refreshAiModels(preferModel = null) {
  const sel  = document.getElementById('ai-model-sel');
  const prev = sel.value;  // capture BEFORE await to avoid race condition
  const d    = await GET('/api/ai/models');
  sel.innerHTML = d.models && d.models.length
    ? d.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('')
    : `<option value="">(no models — click ⬇ Get Model)</option>`;
  if (d.models && d.models.length) {
    // priority: explicit prefer (after download) → previous selection → qwen3-coder → first
    const target = [preferModel, prev,
      d.models.find(m => m.includes('qwen3-coder')),
      d.models[0]
    ].find(m => m && d.models.includes(m));
    if (target) sel.value = target;
  }
  const st = document.getElementById('ai-status');
  if (d.models && d.models.length) {
    st.textContent = `● ${d.models.length} model(s) — ${sel.value}`;
    st.style.color = 'var(--green)';
  } else {
    st.textContent = d.error ? '● ' + d.error : '● No models downloaded';
    st.style.color = d.error ? 'var(--red)' : 'var(--yellow)';
  }
}

document.getElementById('btn-ai-refresh').addEventListener('click', refreshAiModels);
document.getElementById('btn-ai-clear').addEventListener('click', async () => {
  fetch('/api/ai/history', { method: 'DELETE' });
  document.getElementById('chat-view').innerHTML = '';
  aiPartial = ''; aiPending = false; aiStreaming = false; aiAttachText = '';
  document.getElementById('btn-ai-send').disabled = false;
  document.getElementById('btn-ai-stop').disabled = true;
  document.getElementById('ai-attach-bar').classList.add('hidden');
});

document.getElementById('btn-ai-attach').addEventListener('click', () => {
  if (!currentFilePath) { alert('No file open in the editor.'); return; }
  aiAttachText = editor.getValue();
  const bar = document.getElementById('ai-attach-bar');
  document.getElementById('ai-attach-name').textContent =
    '📎 Attached: ' + (currentFilePath.split('/').pop());
  bar.classList.remove('hidden');
  toast('File attached to next AI message.');
});
document.getElementById('btn-ai-detach').addEventListener('click', () => {
  aiAttachText = '';
  document.getElementById('ai-attach-bar').classList.add('hidden');
});

document.getElementById('btn-ai-send').addEventListener('click', sendAiMessage);
document.getElementById('ai-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAiMessage(); }
});

async function sendAiMessage() {
  const input    = document.getElementById('ai-input');
  let   text     = input.value.trim();
  if (!text || aiStreaming) return;
  if (aiAttachText) {
    text += `\n\n--- File: ${currentFilePath.split('/').pop()} ---\n\`\`\`lammps\n${aiAttachText}\n\`\`\``;
    aiAttachText = '';
    document.getElementById('ai-attach-bar').classList.add('hidden');
  }
  const model    = document.getElementById('ai-model-sel').value;
  const cpu_mode = document.getElementById('ai-cpu-chk').checked;
  if (!model) { alert('No model selected. Download one with ⬇ Get Model.'); return; }
  input.value = '';
  appendUserBubble(text);
  aiPartial = ''; aiStreaming = true;
  document.getElementById('btn-ai-send').disabled = true;
  document.getElementById('btn-ai-stop').disabled = false;
  appendAiBubble();
  socket.emit('ai_send', { message: text, model, cpu_mode });
}

document.getElementById('btn-ai-stop').addEventListener('click', () => socket.emit('ai_stop', {}));

socket.on('ai_token', d => {
  aiPartial += d.token;
  if (!aiPending) { aiPending = true; setTimeout(flushAi, 80); }
});
socket.on('ai_done', () => {
  flushAi();
  aiStreaming = false; aiPending = false;
  document.getElementById('btn-ai-send').disabled = false;
  document.getElementById('btn-ai-stop').disabled = true;
  // Finalize — remove streaming class
  const chat = document.getElementById('chat-view');
  chat.querySelectorAll('.bubble-ai-streaming').forEach(el =>
    el.classList.remove('bubble-ai-streaming'));
});
socket.on('ai_error', d => {
  aiStreaming = false;
  document.getElementById('btn-ai-send').disabled = false;
  document.getElementById('btn-ai-stop').disabled = true;
  const chat = document.getElementById('chat-view');
  chat.querySelectorAll('.bubble-ai-streaming').forEach(el => el.remove());
  appendSystemBubble('⚠ Error: ' + d.message +
    (d.message.toLowerCase().includes('cuda') ?
     '\n\nTip: Enable "CPU mode" checkbox — your GPU may not support Ollama kernels.' : ''));
  // Auto-enable CPU mode on CUDA error
  if (d.message.toLowerCase().includes('cuda') || d.message.toLowerCase().includes('device kernel')) {
    document.getElementById('ai-cpu-chk').checked = true;
  }
});

function flushAi() {
  aiPending = false;
  const chat = document.getElementById('chat-view');
  let bubble = chat.querySelector('.bubble-ai-streaming');
  if (!bubble) { appendAiBubble(); bubble = chat.querySelector('.bubble-ai-streaming'); }
  if (!bubble) return;
  const { thinking, response } = splitThink(aiPartial);
  bubble.querySelector('.bubble-body').innerHTML = buildAiHtml(thinking, response, true);
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
    html += `<details class="thinking-block"><summary>💭 Thinking…</summary><div>${esc(thinking)}</div></details>`;
  }
  html += response ? marked.parse(response) :
    (streaming && !thinking ? '<span style="color:var(--fg2)">…</span>' : '');
  return html;
}

function appendUserBubble(text) {
  const chat = document.getElementById('chat-view');
  const div  = document.createElement('div');
  div.className = 'bubble bubble-user';
  div.innerHTML = `<div class="role">You</div><div>${esc(text).replace(/\n/g,'<br>')}</div>`;
  chat.appendChild(div); chat.scrollTop = chat.scrollHeight;
}

function appendAiBubble() {
  const chat = document.getElementById('chat-view');
  const div  = document.createElement('div');
  div.className = 'bubble bubble-ai bubble-ai-streaming';
  div.innerHTML = `<div class="role">AI</div><div class="bubble-body"><span style="color:var(--fg2)">…</span></div>`;
  chat.appendChild(div); chat.scrollTop = chat.scrollHeight;
}

function appendSystemBubble(text) {
  const chat = document.getElementById('chat-view');
  const div  = document.createElement('div');
  div.className = 'bubble bubble-ai';
  div.innerHTML = `<div class="role">System</div><div>${esc(text).replace(/\n/g,'<br>')}</div>`;
  chat.appendChild(div); chat.scrollTop = chat.scrollHeight;
}

// ── Model download dialog ──────────────────────────────────────────────────
document.getElementById('btn-ai-get-model').addEventListener('click', () => {
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.querySelectorAll('#model-table tbody tr').forEach(tr => tr.classList.remove('selected'));
  const rec = document.querySelector('#model-table tr.recommended');
  if (rec) rec.classList.add('selected');
  document.getElementById('modal-custom').value = '';
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
  const st = document.getElementById('ai-status');
  st.textContent = `● Downloading ${model}…`; st.style.color = 'var(--yellow)';
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
  const st = document.getElementById('ai-status');
  if (d.success) {
    refreshAiModels(d.model);
  } else {
    st.textContent = '● Download failed'; st.style.color = 'var(--red)';
    alert('Download failed: ' + (d.error || 'unknown'));
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// Terminal tab
// ═══════════════════════════════════════════════════════════════════════════
let _term = null;
let _termFit = null;

function termSetStatus(msg, color) {
  const el = document.getElementById('term-status');
  el.textContent = msg; el.style.color = color;
}

function termOpen() {
  const container = document.getElementById('terminal-container');
  if (!_term) {
    _term = new Terminal({
      theme: { background: '#0d1117', foreground: '#c9d1d9', cursor: '#58a6ff',
               selectionBackground: '#1f3a5a', black:'#0d1117', brightBlack:'#8b949e',
               red:'#ff7b72', brightRed:'#ffa198', green:'#3fb950', brightGreen:'#56d364',
               yellow:'#d29922', brightYellow:'#e3b341', blue:'#58a6ff', brightBlue:'#79c0ff',
               magenta:'#bc8cff', brightMagenta:'#d2a8ff', cyan:'#39c5cf', brightCyan:'#56d4dd',
               white:'#b1bac4', brightWhite:'#f0f6fc' },
      fontFamily: "'Fira Code','Cascadia Code','Consolas',monospace",
      fontSize: 13, lineHeight: 1.3, cursorBlink: true, scrollback: 5000,
    });
    _termFit = new FitAddon.FitAddon();
    _term.loadAddon(_termFit);
    _term.open(container);
    _term.onData(d => socket.emit('term_input', { data: d }));
  }
  // fit to container
  setTimeout(() => {
    _termFit.fit();
    const { rows, cols } = _term;
    const remote = document.getElementById('term-remote-chk').checked;
    const cwd    = _state_wd || '';
    socket.emit('term_start', { rows, cols, remote, cwd });
    termSetStatus('● Connecting…', 'var(--yellow)');
    document.getElementById('btn-term-connect').disabled    = true;
    document.getElementById('btn-term-disconnect').disabled = false;
  }, 50);
}

let _state_wd = '';  // updated from /api/status

document.getElementById('btn-term-connect').addEventListener('click', termOpen);
document.getElementById('btn-term-disconnect').addEventListener('click', () => {
  socket.emit('term_stop', {});
});
document.getElementById('btn-term-clear').addEventListener('click', () => {
  if (_term) _term.clear();
});

// re-fit terminal when run tab becomes visible
document.querySelectorAll('.tab-btn').forEach(btn => {
  if (btn.dataset.tab === 'run') {
    btn.addEventListener('click', () => {
      setTimeout(() => { if (_term && _termFit) _termFit.fit(); }, 80);
    });
  }
});

// resize observer so terminal fits when panel changes size
(function() {
  const container = document.getElementById('terminal-container');
  if (!container || !window.ResizeObserver) return;
  new ResizeObserver(() => {
    if (_term && _termFit) {
      _termFit.fit();
      socket.emit('term_resize', { rows: _term.rows, cols: _term.cols });
    }
  }).observe(container);
})();

socket.on('term_ready', d => {
  const label = d.remote ? '● SSH shell' : '● Local shell';
  termSetStatus(label, 'var(--green)');
  if (_term) _term.focus();
});
socket.on('term_output', d => { if (_term) _term.write(d.data); });
socket.on('term_exit', () => {
  termSetStatus('● Disconnected', 'var(--fg2)');
  document.getElementById('btn-term-connect').disabled    = false;
  document.getElementById('btn-term-disconnect').disabled = true;
  if (_term) _term.writeln('\r\n\x1b[33m[Terminal closed]\x1b[0m');
});
socket.on('term_error', d => {
  termSetStatus('● Error', 'var(--red)');
  document.getElementById('btn-term-connect').disabled    = false;
  document.getElementById('btn-term-disconnect').disabled = true;
  if (_term) _term.writeln('\r\n\x1b[31m[Error: ' + d.message + ']\x1b[0m');
});

// ═══════════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════════
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function enc(s) { return encodeURIComponent(s); }
async function GET(url) {
  const r = await fetch(url); return r.json();
}
async function POST(url, body) {
  const r = await fetch(url, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body),
  }); return r.json();
}
function toast(msg, ms = 2200) {
  const el = document.createElement('div');
  Object.assign(el.style, {
    position:'fixed', bottom:'20px', right:'20px', padding:'8px 16px',
    background:'#23272b', color:'#4fc3f7', border:'1px solid #2d3139',
    borderRadius:'6px', fontSize:'12px', zIndex:'9999', pointerEvents:'none',
    transition:'opacity .3s',
  });
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; setTimeout(() => el.remove(), 300); }, ms);
}

// ═══════════════════════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════════════════════
(async function init() {
  try { initEditor(); } catch (e) { console.error('Editor init failed:', e); }
  const st = await GET('/api/status').catch(() => ({}));
  const wd = st.working_dir || '';
  _state_wd = wd;
  loadDir(wd || '/home');
  document.getElementById('plot-log-path').value = (wd || '') + '/log.lammps';
  if (wd) document.getElementById('run-dir').value = wd;
  if (st.running) {
    setRunning(true);
    appendLog('▶ [simulation already running — reconnected]', 'log-ok');
  }

  // Restore SSH state
  const ss = await GET('/api/ssh/status').catch(() => ({}));
  if (ss.connected && ss.profile) {
    sshConnected = true;
    document.getElementById('conn-badge').textContent = `⬤ ${ss.profile.name || ss.profile.host}`;
    document.getElementById('conn-badge').className = 'badge badge-on';
    document.getElementById('btn-ssh-connect').disabled    = true;
    document.getElementById('btn-ssh-disconnect').disabled = false;
    document.getElementById('btn-ssh-upload').disabled    = false;
    document.getElementById('btn-ssh-download').disabled  = false;
    setSshStatus(`Connected — ${ss.profile.username}@${ss.profile.host}`, 'var(--green)');
    document.getElementById('ssh-info-body').textContent =
      `Host:    ${ss.profile.host}\nUser:    ${ss.profile.username}\nHome:    ${ss.profile.home || '?'}`;
    // Restore remote file tree to home directory
    loadDir(ss.profile.home || '/', true);
    // Re-run HPC auto-detection so HPC mode toggle is restored
    autoDetectHpc(ss.profile.host);
  }

  updateRunTargetBar();
  refreshAiModels();
})();
