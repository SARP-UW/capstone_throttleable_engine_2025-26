(() => {
	function setSystemMessage(text) {
		const el = document.getElementById('systemMessage');
		if (el) el.textContent = text;
	}

	function setSystemStateValue(text) {
		const el = document.getElementById('systemStateValue');
		if (el) el.textContent = text || 'IDLE';
	}

	let socketRef = null;
	let telemetryFrozen = false;
	let simulationEnabled = true;
	let sequenceDefs = null;
	let systemSnapshot = null;
	let pendingSequenceCommand = null; // 'fill' | 'fire' | null
	let pendingSinceMs = 0;
	let pendingManualExecute = null; // { sequence: string, step_index: number } | null
	let _sequenceRenderScheduled = false;
	let _lastSequenceRenderSig = '';

	function _getSequenceRenderSig(snapshot) {
		const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
		const active = typeof snap.active_sequence === 'string' ? snap.active_sequence : '';
		const current = typeof snap.current_step_index === 'number' ? snap.current_step_index : '';
		const waiting = snap.waiting_manual && typeof snap.waiting_manual === 'object' ? snap.waiting_manual : null;
		const wseq = waiting && typeof waiting.sequence === 'string' ? waiting.sequence : '';
		const widx = waiting && typeof waiting.step_index === 'number' ? waiting.step_index : '';
		const hlen = Array.isArray(snap.history) ? snap.history.length : 0;
		return `${active}|${current}|${wseq}|${widx}|${hlen}`;
	}

	function scheduleRenderSequenceTabs() {
		if (_sequenceRenderScheduled) return;
		_sequenceRenderScheduled = true;
		window.requestAnimationFrame(() => {
			_sequenceRenderScheduled = false;
			renderSequenceTabs();
		});
	}

	function getCompletedStepsSet(history, sequenceKey) {
		const set = new Set();
		if (!Array.isArray(history)) return set;
		for (const rec of history) {
			if (!rec || typeof rec !== 'object') continue;
			if (rec.sequence !== sequenceKey) continue;
			if (rec.status !== 'COMPLETED') continue;
			if (typeof rec.step_index === 'number') set.add(rec.step_index);
		}
		return set;
	}

	function renderSequenceTabs() {
		const host = document.getElementById('sequenceTabs');
		if (!host) return;
		if (!sequenceDefs || !Array.isArray(sequenceDefs)) {
			host.innerHTML = '<div class="sequence-placeholder">Loading sequences...</div>';
			return;
		}

		const snap = systemSnapshot && typeof systemSnapshot === 'object' ? systemSnapshot : {};
		const activeKey = typeof snap.active_sequence === 'string' ? snap.active_sequence : 'idle';
		const currentIdx = typeof snap.current_step_index === 'number' ? snap.current_step_index : null;
		const waiting = snap.waiting_manual && typeof snap.waiting_manual === 'object' ? snap.waiting_manual : null;
		const waitingSeq = waiting && typeof waiting.sequence === 'string' ? waiting.sequence : null;
		const waitingIdx = waiting && typeof waiting.step_index === 'number' ? waiting.step_index : null;
		const isManualStillPending =
			pendingManualExecute &&
			waitingSeq === pendingManualExecute.sequence &&
			waitingIdx === pendingManualExecute.step_index;
		if (pendingManualExecute && !isManualStillPending) pendingManualExecute = null;

		host.innerHTML = '';
		for (const seq of sequenceDefs) {
			if (!seq || typeof seq !== 'object') continue;
			const key = typeof seq.key === 'string' ? seq.key : '';
			const name = typeof seq.name === 'string' ? seq.name : key.toUpperCase();
			const steps = Array.isArray(seq.steps) ? seq.steps : [];

			const details = document.createElement('details');
			// Keep the active sequence expanded by default.
			details.open = key === activeKey;
			const summary = document.createElement('summary');
			summary.textContent = name;
			if (key === activeKey) summary.classList.add('seq-active');
			details.appendChild(summary);

			const completed = getCompletedStepsSet(snap.history, key);
			for (const step of steps) {
				if (!step || typeof step !== 'object') continue;
				const idx = typeof step.index === 'number' ? step.index : null;
				const valve = typeof step.valve === 'string' ? step.valve : '';
				const action = typeof step.action === 'string' ? step.action : '';
				const userInput = !!step.user_input;

				const row = document.createElement('div');
				row.className = 'sequence-step';
				if (key === activeKey && idx !== null && idx === currentIdx) row.classList.add('is-current');

				const left = document.createElement('div');
				left.className = 'step-text';
				let prefix = '';
				if (idx !== null && completed.has(idx)) prefix = '✓ ';
				else if (key === activeKey && idx !== null && idx === currentIdx) prefix = '▶ ';
				else if (waitingSeq === key && idx !== null && idx === waitingIdx) prefix = '⏸ ';

				left.textContent = `${prefix}${valve} ${action}${userInput ? ' (manual)' : ''}`;
				row.appendChild(left);

				const right = document.createElement('div');
				if (waitingSeq === key && idx !== null && idx === waitingIdx) {
					const btn = document.createElement('button');
					btn.type = 'button';
					btn.className = 'mini-btn';
					const pending = pendingManualExecute && pendingManualExecute.sequence === key && pendingManualExecute.step_index === idx;
					btn.textContent = pending ? 'Waiting…' : 'Execute';
					btn.disabled = !!pending;
					btn.addEventListener('click', () => {
						if (!socketRef) {
							setSystemMessage('System message: Not connected (manual execute not sent).');
							return;
						}
						pendingManualExecute = { sequence: key, step_index: idx };
						scheduleRenderSequenceTabs();
						setSystemMessage('System message: Manual execute sent.');
						socketRef.emit('manual_step_execute', { sequence: key, step_index: idx });
					});
					right.appendChild(btn);
				}
				row.appendChild(right);
				details.appendChild(row);
			}

			host.appendChild(details);
		}
	}

	function emitGuiCommand(payload) {
		if (!socketRef) {
			setSystemMessage('System message: Not connected (command not sent).');
			return;
		}
		try {
			socketRef.emit('gui_command', payload);
		} catch (e) {
			console.error('Failed to emit gui_command:', e);
			setSystemMessage('System message: Failed to send command (see console).');
		}
	}

	function getSavedTheme() {
		const t = localStorage.getItem('guiTheme');
		return t === 'dark' || t === 'baja' || t === 'light' ? t : 'light';
	}

	function applyTheme(theme) {
		document.body.classList.remove('theme-dark', 'theme-baja');
		if (theme === 'dark') document.body.classList.add('theme-dark');
		if (theme === 'baja') document.body.classList.add('theme-baja');
		localStorage.setItem('guiTheme', theme);
		updateThemeTicks(theme);
	}

	function updateThemeTicks(theme) {
		document.querySelectorAll('[data-theme-tick]').forEach((el) => {
			const key = el.getAttribute('data-theme-tick');
			el.textContent = key === theme ? '✓' : '';
		});
	}

	function getSavedSimulationEnabled() {
		const raw = localStorage.getItem('simulationEnabled');
		if (raw === 'false') return false;
		if (raw === 'true') return true;
		return true;
	}

	function setSimulationEnabled(enabled) {
		simulationEnabled = !!enabled;
		localStorage.setItem('simulationEnabled', simulationEnabled ? 'true' : 'false');
		updateSimulationTicks(simulationEnabled);
		emitGuiCommand({ name: 'set_simulation', enabled: simulationEnabled });
	}

	function updateSimulationTicks(enabled) {
		const mode = enabled ? 'enabled' : 'disabled';
		document.querySelectorAll('[data-sim-tick]').forEach((el) => {
			const key = el.getAttribute('data-sim-tick');
			el.textContent = key === mode ? '✓' : '';
		});
	}

	const MAX_POINTS = 300;
	const historyBySensor = new Map(); // sensorName -> {t: number[], v: number[], units: string}
	let knownSensorNames = [];

	const plotWidgets = [
		{ canvasId: 'daqPlot1', selectId: 'daqSelect1', defaultSensor: 'thrust' },
		{ canvasId: 'daqPlot2', selectId: 'daqSelect2', defaultSensor: 'tank_temp' },
		{ canvasId: 'daqPlot3', selectId: 'daqSelect3', defaultSensor: 'injector_pressure' },
		{ canvasId: 'daqPlot4', selectId: 'daqSelect4', defaultSensor: 'chamber_pressure' },
		{ canvasId: 'daqPlot5', selectId: 'daqSelect5', defaultSensor: '' },
		{ canvasId: 'daqPlot6', selectId: 'daqSelect6', defaultSensor: '' },
	];

	const bindings = [
		// Keep these two tied to the simulated snapshot keys.
		{ sensorName: 'chamber_pressure', elementId: 'sensor-CC-PT' },
		{ sensorName: 'injector_pressure', elementId: 'sensor-FI-PT' },

		// Untied PTs: expect distinct sensor names from the DAQ state store.
		{ sensorName: 'LF-PT', elementId: 'sensor-LF-PT' },
		{ sensorName: 'FT-PT', elementId: 'sensor-FT-PT' },
		{ sensorName: 'FM-PT', elementId: 'sensor-FM-PT' },
		{ sensorName: 'WM-PT', elementId: 'sensor-WM-PT' },
	];

	const valveStateByName = new Map(); // valveName -> 'open' | 'closed'
	const prevPressureBySensor = new Map(); // sensorName -> { t: number, v: number }

	function resetAllSensorBoxes() {
		document.querySelectorAll('.sensor-box').forEach((el) => {
			el.classList.remove('good');
			el.classList.add('is-placeholder');
			el.innerHTML = '<div class="sensor-reading">-- PSI</div><div class="sensor-deriv">-- psi/min</div>';
		});
	}

	function clearAllPlotHistories() {
		historyBySensor.clear();
		prevPressureBySensor.clear();
		renderAllPlots();
	}

	function setValveUiState(valveName, state) {
		const overlay = document.querySelector(`[data-valve="${CSS.escape(valveName)}"]`);
		if (!overlay) return;
		const status = overlay.querySelector('.status-pill');
		const openBtn = overlay.querySelector('[data-valve-action="open"]');
		const closeBtn = overlay.querySelector('[data-valve-action="close"]');
		const isOpen = state === 'open';

		if (status) status.textContent = isOpen ? 'OPEN' : 'CLOSED';

		if (openBtn instanceof HTMLButtonElement) {
			openBtn.disabled = isOpen;
			openBtn.classList.toggle('is-active-open', isOpen);
			openBtn.classList.toggle('is-active-close', false);
		}
		if (closeBtn instanceof HTMLButtonElement) {
			closeBtn.disabled = !isOpen;
			closeBtn.classList.toggle('is-active-close', !isOpen);
			closeBtn.classList.toggle('is-active-open', false);
		}
	}

	function setValveState(valveName, state) {
		const normalized = state === 'closed' ? 'closed' : 'open';
		valveStateByName.set(valveName, normalized);
		setValveUiState(valveName, normalized);
	}

	function applyValveStatesFromSnapshot(snapshot) {
		const snap = snapshot && typeof snapshot === 'object' ? snapshot : null;
		const valves = snap && snap.valves && typeof snap.valves === 'object' ? snap.valves : null;
		if (!valves) return;
		for (const [k, v] of Object.entries(valves)) {
			if (typeof k !== 'string' || !k) continue;
			if (typeof v !== 'string' || !v) continue;
			setValveState(k, v);
		}
	}

	function initValveControls() {
		document.querySelectorAll('[data-valve]').forEach((overlay) => {
			const valveName = overlay.getAttribute('data-valve');
			if (!valveName) return;
			if (!valveStateByName.has(valveName)) valveStateByName.set(valveName, 'closed');

			const openBtn = overlay.querySelector('[data-valve-action="open"]');
			const closeBtn = overlay.querySelector('[data-valve-action="close"]');
			if (openBtn) {
				openBtn.addEventListener('click', (e) => {
					e.preventDefault();
					emitGuiCommand({ name: 'set_valve', valve: valveName, state: 'open' });
				});
			}
			if (closeBtn) {
				closeBtn.addEventListener('click', (e) => {
					e.preventDefault();
					emitGuiCommand({ name: 'set_valve', valve: valveName, state: 'closed' });
				});
			}

			setValveUiState(valveName, valveStateByName.get(valveName));
		});
	}

	function computePressureRatePsiPerMin(sensorName, tSeconds, valuePsi) {
		if (!sensorName) return null;
		if (!Number.isFinite(tSeconds) || !Number.isFinite(valuePsi)) return null;
		const prev = prevPressureBySensor.get(sensorName);
		prevPressureBySensor.set(sensorName, { t: tSeconds, v: valuePsi });
		if (!prev) return null;
		const dt = tSeconds - prev.t;
		if (!(dt > 0)) return null;
		// psi/min
		return ((valuePsi - prev.v) / dt) * 60;
	}

	function setPressureBox(el, valuePsi, ratePsiPerMin) {
		if (!el) return;
		el.classList.remove('is-placeholder');
		const rounded = Math.round(valuePsi);
		const rateText = Number.isFinite(ratePsiPerMin)
			? `${ratePsiPerMin >= 0 ? '+' : ''}${ratePsiPerMin.toFixed(1)} psi/min`
			: '-- psi/min';
		el.innerHTML = `<div class="sensor-reading">${rounded} PSI</div><div class="sensor-deriv">${rateText}</div>`;

		const thresholdStr = el.dataset.greenThresholdPsi;
		const thresholdPsi = thresholdStr ? Number(thresholdStr) : NaN;
		const isGood = Number.isFinite(thresholdPsi) ? valuePsi <= thresholdPsi : false;
		el.classList.toggle('good', isGood);
	}

	function getDaqStageVisible() {
		const stage = document.getElementById('daqStage');
		return !!stage && !stage.classList.contains('hidden');
	}

	function resizeCanvasToDisplaySize(canvas) {
		if (!canvas) return false;
		const dpr = window.devicePixelRatio || 1;
		const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
		const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
		if (canvas.width !== width || canvas.height !== height) {
			canvas.width = width;
			canvas.height = height;
			return true;
		}
		return false;
	}

	function setSelectOptions(selectEl, sensorNames) {
		if (!selectEl) return;

		const current = selectEl.value;
		selectEl.innerHTML = '';

		const emptyOpt = document.createElement('option');
		emptyOpt.value = '';
		emptyOpt.textContent = '— select signal —';
		selectEl.appendChild(emptyOpt);

		for (const name of sensorNames) {
			const opt = document.createElement('option');
			opt.value = name;
			opt.textContent = name;
			selectEl.appendChild(opt);
		}

		if (sensorNames.includes(current)) {
			selectEl.value = current;
		}
	}

	function updateAllSelectOptionsIfNeeded(sensorNames) {
		const same = sensorNames.length === knownSensorNames.length && sensorNames.every((v, i) => v === knownSensorNames[i]);
		if (same) return;
		knownSensorNames = sensorNames;
		for (const w of plotWidgets) {
			const selectEl = document.getElementById(w.selectId);
			setSelectOptions(selectEl, knownSensorNames);
			if (w.defaultSensor && selectEl && (!selectEl.value || selectEl.value === '')) {
				if (knownSensorNames.includes(w.defaultSensor)) selectEl.value = w.defaultSensor;
			}
		}
	}

	function ingestPacketForPlots(packet) {
		if (!packet || typeof packet !== 'object') return;
		const states = packet.states;
		if (!states || typeof states !== 'object') return;

		const tWall = typeof packet.t_wall === 'number' ? packet.t_wall : Date.now() / 1000;
		const sensorNames = Object.keys(states).sort();
		updateAllSelectOptionsIfNeeded(sensorNames);

		for (const name of sensorNames) {
			const state = states[name];
			if (!state || typeof state !== 'object') continue;
			const value = state.value;
			if (typeof value !== 'number') continue;
			const units = typeof state.units === 'string' ? state.units : '';

			let rec = historyBySensor.get(name);
			if (!rec) {
				rec = { t: [], v: [], units };
				historyBySensor.set(name, rec);
			}
			if (units) rec.units = units;

			rec.t.push(tWall);
			rec.v.push(value);
			if (rec.t.length > MAX_POINTS) {
				rec.t.splice(0, rec.t.length - MAX_POINTS);
				rec.v.splice(0, rec.v.length - MAX_POINTS);
			}
		}
	}

	function drawPlot(canvas, sensorName) {
		if (!canvas) return;
		resizeCanvasToDisplaySize(canvas);
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const w = canvas.width;
		const h = canvas.height;

		// Background
		ctx.fillStyle = '#ffffff';
		ctx.fillRect(0, 0, w, h);
		ctx.strokeStyle = '#666666';
		ctx.lineWidth = 2;
		ctx.strokeRect(0, 0, w, h);

		if (!sensorName) {
			ctx.fillStyle = '#111111';
			ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
			ctx.fillText('Select a signal', Math.floor(w * 0.05), Math.floor(h * 0.18));
			return;
		}

		const rec = historyBySensor.get(sensorName);
		if (!rec || rec.t.length < 2) {
			ctx.fillStyle = '#111111';
			ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
			ctx.fillText(`${sensorName}: waiting for data...`, Math.floor(w * 0.05), Math.floor(h * 0.18));
			return;
		}

		const pad = Math.max(10, Math.floor(Math.min(w, h) * 0.08));
		const left = pad;
		const right = w - pad;
		const top = pad;
		const bottom = h - pad;

		let minV = Infinity;
		let maxV = -Infinity;
		for (const v of rec.v) {
			if (v < minV) minV = v;
			if (v > maxV) maxV = v;
		}
		if (!Number.isFinite(minV) || !Number.isFinite(maxV)) return;
		if (minV === maxV) {
			const bump = minV === 0 ? 1 : Math.abs(minV) * 0.1;
			minV -= bump;
			maxV += bump;
		}

		const t0 = rec.t[0];
		const t1 = rec.t[rec.t.length - 1];
		const dt = t1 - t0 || 1;

		// Axes
		ctx.strokeStyle = '#666666';
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(left, top);
		ctx.lineTo(left, bottom);
		ctx.lineTo(right, bottom);
		ctx.stroke();

		// Line
		ctx.strokeStyle = '#2957ff';
		ctx.lineWidth = 2;
		ctx.beginPath();
		for (let i = 0; i < rec.t.length; i++) {
			const x = left + ((rec.t[i] - t0) / dt) * (right - left);
			const yNorm = (rec.v[i] - minV) / (maxV - minV);
			const y = bottom - yNorm * (bottom - top);
			if (i === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.stroke();

		// Title / latest value
		const latestV = rec.v[rec.v.length - 1];
		const units = rec.units ? ` ${rec.units}` : '';
		ctx.fillStyle = '#111111';
		ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
		ctx.fillText(`${sensorName}: ${latestV.toFixed(2)}${units}`, left, Math.max(top - 6, Math.floor(h * 0.12)));
	}

	function renderAllPlots() {
		if (!getDaqStageVisible()) return;
		for (const w of plotWidgets) {
			const canvas = document.getElementById(w.canvasId);
			const selectEl = document.getElementById(w.selectId);
			const sensorName = selectEl ? selectEl.value : '';
			drawPlot(canvas, sensorName);
		}
	}

	function initDaqControls() {
		for (const w of plotWidgets) {
			const selectEl = document.getElementById(w.selectId);
			if (!selectEl) continue;
			if (!selectEl.querySelector('option')) {
				const opt = document.createElement('option');
				opt.value = '';
				opt.textContent = 'Waiting for data...';
				selectEl.appendChild(opt);
			}
			selectEl.addEventListener('change', () => renderAllPlots());
		}

		document.querySelectorAll('.tab[data-tab="daq"]').forEach((t) => {
			t.addEventListener('click', () => {
				// Defer to allow DOM to update visibility.
				setTimeout(() => renderAllPlots(), 0);
			});
		});

		window.addEventListener('resize', () => renderAllPlots());
	}

	function applyPacket(packet) {
		if (telemetryFrozen) return;
		if (!packet || typeof packet !== 'object') return;
		const states = packet.states;
		if (!states || typeof states !== 'object') return;

		const fallbackT = typeof packet.t_wall === 'number' ? packet.t_wall : Date.now() / 1000;
		const pressureRateBySensorName = new Map();

		for (const { sensorName, elementId } of bindings) {
			const state = states[sensorName];
			if (!state || typeof state !== 'object') continue;
			const value = state.value;
			if (typeof value !== 'number') continue;
			const t = typeof state.t_monotonic === 'number' ? state.t_monotonic : fallbackT;
			let rate = pressureRateBySensorName.get(sensorName);
			if (rate === undefined) {
				rate = computePressureRatePsiPerMin(sensorName, t, value);
				pressureRateBySensorName.set(sensorName, rate);
			}
			const el = document.getElementById(elementId);
			setPressureBox(el, value, rate);
		}

		ingestPacketForPlots(packet);
		renderAllPlots();
	}

	function connectSocket() {
		if (typeof window.io !== 'function') {
			console.error('Socket.IO client not loaded (window.io missing).');
			setSystemMessage('System message: Socket.IO client failed to load (check internet/CDN).');
			return;
		}

		// If the user opens the HTML directly (file://) or via a different server,
		// `io()` will try to connect to the wrong origin. Default to the GUI server.
		let socketUrl;
		try {
			const explicit = typeof window.__BACKEND_SOCKET_URL__ === 'string' ? window.__BACKEND_SOCKET_URL__.trim() : '';
			if (explicit) socketUrl = explicit;
		} catch (_) {
			// ignore
		}
		try {
			// Two-process default: if the GUI is being served on :5000, the backend
			// Socket.IO server is expected on the same host at :6001.
			if (!socketUrl && window.location && window.location.protocol && window.location.hostname) {
				if (window.location.protocol !== 'file:' && window.location.port !== '6001') {
					socketUrl = `${window.location.protocol}//${window.location.hostname}:6001`;
				}
			}
		} catch (_) {
			// ignore
		}
		try {
			if (!socketUrl && (window.location.protocol === 'file:' || !window.location.hostname)) {
				socketUrl = 'http://127.0.0.1:6001';
			}
		} catch (_) {
			if (!socketUrl) socketUrl = 'http://127.0.0.1:6001';
		}

		const socketOpts = {
			path: '/socket.io',
			transports: ['websocket', 'polling'],
			timeout: 5000,
		};
		const socket = socketUrl ? window.io(socketUrl, socketOpts) : window.io(socketOpts);
		socketRef = socket;
		socket.on('connect', () => {
			setSystemMessage('System message: Connected to DAQ stream.');

			emitGuiCommand({ name: 'set_simulation', enabled: simulationEnabled });
		});
		socket.on('disconnect', () => {
			setSystemMessage('System message: Disconnected from DAQ stream.');
		});
		socket.on('connect_error', (err) => {
			console.error('Socket connect_error:', err);
			const detail = (err && (err.message || err.description)) ? (err.message || err.description) : String(err);
			setSystemMessage(`System message: Socket connect error: ${detail}`);
		});

		socket.on('command_accept', (msg) => {
			if (msg && msg.name) setSystemMessage(`System message: Command accepted (${msg.name}).`);
			if (msg && msg.name === 'manual_step_execute') {
				// Clear the local pending flag once the backend has accepted the request.
				// The Execute button itself is still gated by `system_packet.waiting_manual`.
				pendingManualExecute = null;
				scheduleRenderSequenceTabs();
			}
		});
		socket.on('command_reject', (msg) => {
			const reason = msg && msg.reason ? msg.reason : 'unknown';
			setSystemMessage(`System message: Command rejected (${reason}).`);
			if (pendingSequenceCommand) {
				pendingSequenceCommand = null;
				pendingSinceMs = 0;
				const fillBtn = document.getElementById('fillBtn');
				const fireBtn = document.getElementById('fireBtn');
				if (fillBtn) fillBtn.disabled = false;
				if (fireBtn) fireBtn.disabled = false;
			}
			if (pendingManualExecute) {
				pendingManualExecute = null;
				renderSequenceTabs();
			}
		});
		socket.on('system_message', (msg) => {
			const text = msg && msg.text ? msg.text : '';
			if (text) setSystemMessage(`System message: ${text}`);
		});

		socket.on('sequence_definitions', (msg) => {
			const seqs = msg && Array.isArray(msg.sequences) ? msg.sequences : null;
			if (seqs !== null) {
				sequenceDefs = seqs;
				_lastSequenceRenderSig = '';
				scheduleRenderSequenceTabs();
			}
		});

		socket.on('system_packet', (pkt) => {
			systemSnapshot = pkt && typeof pkt === 'object' ? pkt : null;
			const state = systemSnapshot && typeof systemSnapshot.system_state === 'string' ? systemSnapshot.system_state : 'IDLE';
			setSystemStateValue(state);
			applyValveStatesFromSnapshot(systemSnapshot);
			const sig = _getSequenceRenderSig(systemSnapshot);
			if (sig !== _lastSequenceRenderSig) {
				_lastSequenceRenderSig = sig;
				scheduleRenderSequenceTabs();
			}

			// Handshake: if we have a pending Fill/Fire, wait until the backend
			// reports the sequence as active.
			if (pendingSequenceCommand) {
				const active = systemSnapshot && typeof systemSnapshot.active_sequence === 'string' ? systemSnapshot.active_sequence : '';
				if (active === pendingSequenceCommand) {
					pendingSequenceCommand = null;
					pendingSinceMs = 0;
					const fillBtn = document.getElementById('fillBtn');
					const fireBtn = document.getElementById('fireBtn');
					if (fillBtn) fillBtn.disabled = false;
					if (fireBtn) fireBtn.disabled = false;
				}
			}
		});

		socket.on('manual_step_required', (msg) => {
			const text = msg && msg.message ? msg.message : 'Manual step required.';
			setSystemMessage(`System message: ${text}`);
			// The UI will also show an Execute button via system_packet.waiting_manual.
		});

		socket.on('daq_packet', (pkt) => {
			applyPacket(pkt);
		});
	}

	function initTestButtons() {
		const startBtn = document.getElementById('startLogBtn');
		if (startBtn) {
			startBtn.addEventListener('click', () => {
				telemetryFrozen = false;
				emitGuiCommand({ name: 'start_log' });
			});
		}
		const stopBtn = document.getElementById('stopLogBtn');
		if (stopBtn) {
			stopBtn.addEventListener('click', () => {
				telemetryFrozen = true;
				emitGuiCommand({ name: 'stop_log' });
			});
		}

		const fillBtn = document.getElementById('fillBtn');
		if (fillBtn) {
			fillBtn.addEventListener('click', () => {
				pendingSequenceCommand = 'fill';
				pendingSinceMs = Date.now();
				fillBtn.disabled = true;
				const fireBtn = document.getElementById('fireBtn');
				if (fireBtn) fireBtn.disabled = true;
				setSystemMessage('System message: Fill requested; waiting for backend state change...');
				emitGuiCommand({ name: 'fill' });
			});
		}

		const fireBtn = document.getElementById('fireBtn');
		if (fireBtn) {
			fireBtn.addEventListener('click', () => {
				pendingSequenceCommand = 'fire';
				pendingSinceMs = Date.now();
				fireBtn.disabled = true;
				const fillBtn = document.getElementById('fillBtn');
				if (fillBtn) fillBtn.disabled = true;
				setSystemMessage('System message: Fire requested; waiting for backend state change...');
				emitGuiCommand({ name: 'fire' });
			});
		}

		const clearBtn = document.getElementById('clearTestBtn');
		if (clearBtn) {
			clearBtn.addEventListener('click', () => {
				resetAllSensorBoxes();
				clearAllPlotHistories();
				if (simulationEnabled) {
					pendingSequenceCommand = null;
					pendingSinceMs = 0;
					pendingManualExecute = null;
					const fillBtn = document.getElementById('fillBtn');
					const fireBtn = document.getElementById('fireBtn');
					if (fillBtn) fillBtn.disabled = false;
					if (fireBtn) fireBtn.disabled = false;
					emitGuiCommand({ name: 'reset_sequences' });
					setSystemMessage('System message: Cleared test + reset sequences (SIM mode).');
				}
			});
		}
	}

	function initSettingsMenu() {
		const toggle = document.getElementById('settingsToggle');
		const menu = document.getElementById('settingsMenu');
		const themeSubmenu = document.getElementById('themeSubmenu');
		const simSubmenu = document.getElementById('simulationSubmenu');
		if (!toggle || !menu) return;

		function closeMenu() {
			menu.classList.add('hidden');
			toggle.setAttribute('aria-expanded', 'false');
			if (themeSubmenu) themeSubmenu.classList.add('hidden');
			if (simSubmenu) simSubmenu.classList.add('hidden');
		}

		function openMenu() {
			menu.classList.remove('hidden');
			toggle.setAttribute('aria-expanded', 'true');
		}

		function toggleMenu() {
			if (menu.classList.contains('hidden')) openMenu();
			else closeMenu();
		}

		function showSubmenu(which) {
			if (themeSubmenu) themeSubmenu.classList.toggle('hidden', which !== 'theme');
			if (simSubmenu) simSubmenu.classList.toggle('hidden', which !== 'simulation');
		}

		toggle.addEventListener('click', (e) => {
			e.stopPropagation();
			toggleMenu();
		});

		document.querySelectorAll('[data-settings-section]').forEach((btn) => {
			btn.addEventListener('click', (e) => {
				e.stopPropagation();
				openMenu();
				showSubmenu(btn.getAttribute('data-settings-section'));
			});
		});

		document.querySelectorAll('[data-theme]').forEach((btn) => {
			btn.addEventListener('click', (e) => {
				e.stopPropagation();
				applyTheme(btn.getAttribute('data-theme'));
			});
		});

		document.querySelectorAll('[data-simulation]').forEach((btn) => {
			btn.addEventListener('click', (e) => {
				e.stopPropagation();
				const mode = btn.getAttribute('data-simulation');
				setSimulationEnabled(mode === 'enabled');
			});
		});

		document.addEventListener('click', closeMenu);
		document.addEventListener('keydown', (e) => {
			if (e.key === 'Escape') closeMenu();
		});
	}

	window.addEventListener('load', () => {
		simulationEnabled = getSavedSimulationEnabled();
		applyTheme(getSavedTheme());
		updateSimulationTicks(simulationEnabled);
		resetAllSensorBoxes();
		initSettingsMenu();
		initDaqControls();
		initTestButtons();
		initValveControls();
		connectSocket();
	});
})();
