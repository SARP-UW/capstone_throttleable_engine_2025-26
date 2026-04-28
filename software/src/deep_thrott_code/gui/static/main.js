(() => {
	function setSystemMessage(text) {
		const el = document.getElementById('systemMessage');
		if (el) el.textContent = text;
	}

	let socketRef = null;
	let telemetryFrozen = false;
	let simulationEnabled = true;

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

	function initValveControls() {
		document.querySelectorAll('[data-valve]').forEach((overlay) => {
			const valveName = overlay.getAttribute('data-valve');
			if (!valveName) return;
			if (!valveStateByName.has(valveName)) valveStateByName.set(valveName, 'open');

			const openBtn = overlay.querySelector('[data-valve-action="open"]');
			const closeBtn = overlay.querySelector('[data-valve-action="close"]');
			if (openBtn) {
				openBtn.addEventListener('click', (e) => {
					e.preventDefault();
					setValveState(valveName, 'open');
				});
			}
			if (closeBtn) {
				closeBtn.addEventListener('click', (e) => {
					e.preventDefault();
					setValveState(valveName, 'closed');
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
			if (window.location.protocol === 'file:' || !window.location.hostname) {
				socketUrl = 'http://127.0.0.1:5000';
			}
		} catch (_) {
			socketUrl = 'http://127.0.0.1:5000';
		}

		const socketOpts = {
			path: '/socket.io',
			transports: ['polling'],
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
		});
		socket.on('command_reject', (msg) => {
			const reason = msg && msg.reason ? msg.reason : 'unknown';
			setSystemMessage(`System message: Command rejected (${reason}).`);
		});
		socket.on('system_message', (msg) => {
			const text = msg && msg.text ? msg.text : '';
			if (text) setSystemMessage(`System message: ${text}`);
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
				emitGuiCommand({ name: 'fill' });
			});
		}

		const fireBtn = document.getElementById('fireBtn');
		if (fireBtn) {
			fireBtn.addEventListener('click', () => {
				emitGuiCommand({ name: 'fire' });
			});
		}

		const clearBtn = document.getElementById('clearTestBtn');
		if (clearBtn) {
			clearBtn.addEventListener('click', () => {
				resetAllSensorBoxes();
				clearAllPlotHistories();
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
